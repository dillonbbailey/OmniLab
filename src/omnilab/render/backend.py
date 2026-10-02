"""Native runtime adapter. Import this module only in a worker or GPU probe."""
import time

import numpy as np
import ovrtx
import ovstage


class Backend:
    def __init__(self, log_path):
        self.renderer = ovrtx.Renderer(config=ovrtx.RendererConfig(
            log_file_path=str(log_path), active_cuda_gpus="0", selection_outline_enabled=True,
            selection_outline_width=2))
        self.stage = None
        self.ordinal = 0
        self.snapshot = None
        self.selection = []
        self.renderer.set_selection_group_styles({1: ovrtx.SelectionGroupStyle(
            outline_color=(1., .6, .1, 1.), fill_color=(0., 0., 0., 0.))})

    def load(self, snapshot):
        if self.stage is not None:
            self.renderer.detach_ovstage()
            self.stage.destroy()
            self.stage = None
        self.stage = ovstage.Stage("omnilab.viewport")
        self.renderer.attach_ovstage(self.stage)
        self.ordinal = 1
        started = time.perf_counter()
        ovstage.population.open_usd(self.stage, snapshot["path"], ordinal=self.ordinal,
                                   time_code=snapshot["frame"] / snapshot["time_codes_per_second"])
        self.stage.advance_write_floor(self.ordinal, ovstage.Scope.ALL).wait()
        self.snapshot = snapshot
        self.selection = []
        self.renderer.reset()
        return (time.perf_counter() - started) * 1000

    def write(self, path, attribute, value, dtype, lanes=1, semantic=None):
        """One scalar/vector/matrix write at the current open ordinal."""
        array = np.asarray(value, dtype=dtype).reshape((1, -1))
        with ovstage.PathDictionary(self.stage) as paths:
            path_list = paths.create_path_list_from_strings([path])
            query = self.stage.query_from_path_list(path_list)
            try:
                tensor = ovstage.make_dltensor(array, dtype=ovstage.numpy_to_dldatatype(array.dtype, lanes=lanes),
                                               shape=[1], ndim=1)
                kwargs = dict(semantic=semantic) if semantic is not None else {}
                self.stage.write_attribute(query, paths.intern_token(attribute), ordinal=self.ordinal,
                                           tensors=tensor, is_array=False, **kwargs).wait()
            finally:
                query.release().wait()
                paths.destroy_path_list(path_list)

    def update_camera(self, data):
        self.ordinal += 1
        path = self.snapshot["camera"]
        self.write(path, "omni:xform", data["matrix"], np.float64, 16)
        for key in ("horizontalAperture", "verticalAperture", "focalLength"):
            self.write(path, key, data[key], np.float32)
        self.write(path, "clippingRange", data["clippingRange"], np.float32, 2)
        self.stage.advance_write_floor(self.ordinal, ovstage.Scope.ALL).wait()
        self.renderer.reset()

    def set_selection(self, paths):
        if self.selection:
            self.renderer.set_selection_outline_group_strings(self.selection, 0)
        self.selection = list(paths)
        if self.selection:
            self.renderer.set_selection_outline_group_strings(self.selection, 1)

    def update_attributes(self, edits):
        self.ordinal += 1
        for edit in edits:
            self.write(edit["path"], edit["attribute"], edit["value"], np.dtype(edit["dtype"]), edit["lanes"])
        self.stage.advance_write_floor(self.ordinal, ovstage.Scope.ALL).wait()
        self.renderer.reset()

    def render(self, pick=None):
        if pick:
            self.renderer.enqueue_pick_query(render_product_path=self.snapshot["product"],
                left_ndc=pick[0], top_ndc=pick[1], right_ndc=pick[2], bottom_ndc=pick[3])
        started = time.perf_counter()
        products = self.renderer.step(render_products={self.snapshot["product"]}, delta_time=1 / 60,
                                      ordinal=self.ordinal)
        frame = products[self.snapshot["product"]].frames[-1]
        outputs = {}
        for path, var in frame.render_vars.items():
            if path == ovrtx.OVRTX_RENDER_VAR_PICK_HIT:
                continue
            mapping = var.map(device=ovrtx.Device.CPU)
            try:
                view = np.from_dlpack(mapping)
                outputs[path.rsplit("/", 1)[-1]] = view.copy()
                del view
            finally:
                mapping.unmap()
        hits = []
        if pick:
            mapping = frame.render_vars[ovrtx.OVRTX_RENDER_VAR_PICK_HIT].map(device=ovrtx.Device.CPU)
            try:
                magic = int(np.from_dlpack(mapping.params["magic"]).reshape(-1)[0])
                version = int(np.from_dlpack(mapping.params["version"]).reshape(-1)[0])
                count = int(np.from_dlpack(mapping.params["hitCount"]).reshape(-1)[0])
                ids = np.from_dlpack(mapping["primPath"]).copy().reshape(-1)[:count]
                positions = np.from_dlpack(mapping["worldPositionM"]).copy().reshape((-1, 3))[:count]
            finally:
                mapping.unmap()
            if magic != ovrtx.OVRTX_PICK_HIT_MAGIC or version != ovrtx.OVRTX_PICK_HIT_VERSION:
                raise RuntimeError("Unsupported native pick-hit schema.")
            for path_id, position in zip(ids, positions):
                path = self.renderer.resolve_prim_path_id(int(path_id))
                if path:
                    hits.append(dict(path=path, position=position.tolist()))
        duration = (time.perf_counter() - started) * 1000
        del frame, products
        return outputs, hits, duration

    def close(self):
        if self.stage is not None:
            self.renderer.detach_ovstage()
            self.stage.destroy()
            self.stage = None
        self.renderer.destroy()
