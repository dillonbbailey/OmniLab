"""Run with the Python version matching NVIDIA's separately installed bindings.

Only JSON crosses this process boundary; neither SDK objects nor native libraries
are loaded into the Qt/authoring interpreter.
"""
import gc
import json
from pathlib import Path
import sys


def inspect(request):
    root = Path(request['sdk'])
    sys.path.insert(0, str(root / 'lib/python'))
    import pymdlsdk as sdk

    def value(item):
        if not item or not item.is_valid_interface():
            return None
        kind = item.get_kind()
        for name in ['bool', 'int', 'float', 'double', 'string', 'enumeration']:
            token = 'ENUM' if name == 'enumeration' else name.upper()
            if kind == getattr(sdk.IValue.Kind, 'VK_' + token):
                with item.get_interface(getattr(sdk, 'IValue_' + name)) as typed:
                    return typed.get_value()
        for name in ['color', 'vector', 'matrix', 'array']:
            if kind == getattr(sdk.IValue.Kind, 'VK_' + name.upper()):
                with item.get_interface(getattr(sdk, 'IValue_' + name)) as typed:
                    return [value(typed.get_value(i)) for i in range(typed.get_size())]
        if kind == sdk.IValue.Kind.VK_TEXTURE:
            return ''
        return None

    def constant(expression):
        if expression and expression.is_valid_interface() and expression.get_kind() == sdk.IExpression.Kind.EK_CONSTANT:
            with expression.get_interface(sdk.IExpression_constant) as typed:
                return value(typed.get_value())
        return None

    def annotations(block):
        result = {}
        if block and block.is_valid_interface():
            for index in range(block.get_size()):
                with block.get_annotation(index) as annotation, annotation.get_arguments() as arguments:
                    result[annotation.get_name()] = {arguments.get_name(i): constant(arguments.get_expression(i))
                                                    for i in range(arguments.get_size())}
        return result

    def reflect(neuray):
        with neuray.get_api_component(sdk.IDatabase) as database, database.get_global_scope() as scope:
            with scope.create_transaction() as transaction:
                with neuray.get_api_component(sdk.IMdl_factory) as factory, \
                     neuray.get_api_component(sdk.IMdl_impexp_api) as impexp, \
                     factory.create_execution_context() as context:
                    with impexp.get_mdl_module_name(request['module']) as module_name:
                        if not module_name.is_valid_interface():
                            raise ValueError('The MDL module is outside the configured search paths.')
                        mdl_name = module_name.get_c_str()
                    result = impexp.load_module(transaction, mdl_name, context)
                    messages = [context.get_message(i).get_string() for i in range(context.get_messages_count())]
                    if result < 0 or context.get_error_messages_count():
                        raise ValueError('\n'.join(messages) or f'MDL load failed ({result}).')
                    with factory.get_db_module_name(mdl_name) as db_name, \
                         transaction.access_as(sdk.IModule, db_name.get_c_str()) as module:
                        names = [module.get_material(i) for i in range(module.get_material_count())]
                        names += [module.get_function(i) for i in range(module.get_function_count())]
                        definitions = []
                        with factory.create_type_factory(transaction) as types:
                            for name in names:
                                with transaction.access_as(sdk.IFunction_definition, name) as function:
                                    if not function.is_exported():
                                        continue
                                    with function.get_parameter_types() as parameters, function.get_defaults() as defaults, \
                                         function.get_parameter_annotations() as metadata:
                                        inputs = []
                                        for index in range(function.get_parameter_count()):
                                            parameter = function.get_parameter_name(index)
                                            with parameters.get_type(parameter) as type_, type_.skip_all_type_aliases() as canonical, types.dump(canonical) as type_text:
                                                inputs.append(dict(name=parameter, type=type_text.get_c_str(),
                                                    default=constant(defaults.get_expression(parameter)),
                                                    annotations=annotations(metadata.get_annotation_block(parameter))))
                                        with function.get_return_type() as return_type, types.dump(return_type) as return_text:
                                            definitions.append(dict(name=function.get_mdl_simple_name(), signature=function.get_mdl_name(),
                                                material=function.is_material(), return_type=return_text.get_c_str(),
                                                inputs=inputs, annotations=annotations(function.get_annotations())))
                        if request.get('runtime_module'):
                            with factory.create_module_transformer(transaction, db_name.get_c_str(), context) as transformer:
                                if transformer.inline_imported_modules(None, None, True, context) != 0:
                                    raise ValueError('MDL import inlining failed: ' + '\n'.join(context.get_message(i).get_string() for i in range(context.get_messages_count())))
                                context.set_option('bundle_resources', True)
                                if transformer.export_module(request['runtime_module'], context) != 0:
                                    raise ValueError('MDL dependency export failed: ' + '\n'.join(context.get_message(i).get_string() for i in range(context.get_messages_count())))
                        output = dict(module=request['module'], mdl_name=mdl_name, definitions=definitions, messages=messages)
                transaction.commit()
                return output

    neuray = sdk.load_and_get_ineuray(str(root / 'lib/libmdl_sdk.so'))
    if not neuray.is_valid_interface():
        raise RuntimeError('Could not load the MDL SDK. Check the SDK and Python binding versions.')
    started = False
    failure = None
    output = None
    try:
        with neuray.get_api_component(sdk.IMdl_configuration) as configuration:
            for path in request['search_paths']:
                if configuration.add_mdl_path(path) != 0:
                    raise ValueError('Invalid MDL search path: ' + path)
        for plugin in ['nv_openimageio.so', 'dds.so']:
            if (root / 'lib' / plugin).exists():
                sdk.load_plugin(neuray, str(root / 'lib' / plugin))
        if neuray.start() != 0:
            raise RuntimeError('The MDL SDK failed to start.')
        started = True
        output = reflect(neuray)
    except Exception as error:
        # Do not unload the DLL while an active traceback owns SDK interfaces.
        # Release the exception frame first, then collect and shut down.
        while error.__context__ is not None:
            error = error.__context__
        failure = str(error)
    finally:
        gc.collect()
        if started and neuray.shutdown() != 0 and not failure:
            failure = 'The MDL SDK failed to shut down cleanly.'
        neuray = None
        gc.collect()
        sdk.unload()
    if failure:
        raise RuntimeError(failure)
    return output


if __name__ == '__main__':
    request_path, output_path = map(Path, sys.argv[1:])
    try:
        result = dict(status='passed', **inspect(json.loads(request_path.read_text())))
    except Exception as error:
        result = dict(status='failed', error=str(error))
    output_path.write_text(json.dumps(result, indent=2) + '\n')
    sys.exit(0 if result['status'] == 'passed' else 1)
