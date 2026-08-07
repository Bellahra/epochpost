#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""epochpost: 通用 EPOCH PIC 后处理工具，使用 sdf_xarray。

日常使用时不需要修改本文件；绘图任务、数据目录、论文绘图样式和输出参数
均写在 ``epochpost_input.json`` 中。

运行：
    python new.py
    python new.py epochpost_input.json

也可以作为模块调用：
    from new import run_config
    run_config("epochpost_input.json")
"""

from pathlib import Path
import argparse
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.colors import LogNorm, Normalize, SymLogNorm
import numpy as np
from scipy.constants import c, e, epsilon_0, m_e
import sdf_xarray as sx


# 运行时配置。run_config() 会根据 JSON 更新这些量。
DATA_DIR = Path("Data")
OUT_DIR = DATA_DIR / "postprocess"
LASER_WAVELENGTH_NM = 800.0
SPACE_UNIT = "nm"
SPACE_FACTOR = 1.0e9
TIME_UNIT = "fs"
TIME_FACTOR = 1.0e15

# 论文绘图默认参数。settings.plot 可以全局覆盖；task.plot 可以单图覆盖。
PLOT_DEFAULTS = {
    "format": "png",
    "dpi": 300,
    "fig_single": [3.4, 2.7],
    "fig_double": [7.0, 4.8],
    "font_family": "Arial",
    "mathtext_fontset": "stix",
    "font_label": 10,
    "font_tick": 8,
    "font_legend": 8,
    "font_panel": 11,
    "font_annotation": 8,
    "line_width": 1.5,
    "axis_width": 1.0,
    "bbox_inches": "tight",
}
PLOT_SETTINGS = dict(PLOT_DEFAULTS)
# 保留 DPI 全局量，兼容旧代码/外部调用。
DPI = int(PLOT_DEFAULTS["dpi"])

NC = None
J0 = None


def _update_derived_constants():
    global NC, J0
    wavelength_m = LASER_WAVELENGTH_NM * 1.0e-9
    omega0 = 2.0 * np.pi * c / wavelength_m
    NC = epsilon_0 * m_e * omega0**2 / e**2
    J0 = e * NC * c


_update_derived_constants()


def _resolve_path(value, base_dir):
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _validate_pair(value, name):
    """把 [width, height] 一类配置转换为两个正浮点数。"""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} 必须是长度为 2 的数组，例如 [3.4, 2.7]")
    pair = [float(value[0]), float(value[1])]
    if pair[0] <= 0 or pair[1] <= 0:
        raise ValueError(f"{name} 中的尺寸必须 > 0")
    return pair


def _apply_plot_style():
    """把全局论文绘图规范应用到 Matplotlib。"""
    plt.rcParams.update({
        "font.family": PLOT_SETTINGS["font_family"],
        "mathtext.fontset": PLOT_SETTINGS["mathtext_fontset"],
        "font.size": float(PLOT_SETTINGS["font_annotation"]),
        "axes.labelsize": float(PLOT_SETTINGS["font_label"]),
        "axes.titlesize": float(PLOT_SETTINGS["font_panel"]),
        "figure.titlesize": float(PLOT_SETTINGS["font_panel"]),
        "xtick.labelsize": float(PLOT_SETTINGS["font_tick"]),
        "ytick.labelsize": float(PLOT_SETTINGS["font_tick"]),
        "legend.fontsize": float(PLOT_SETTINGS["font_legend"]),
        "lines.linewidth": float(PLOT_SETTINGS["line_width"]),
        "axes.linewidth": float(PLOT_SETTINGS["axis_width"]),
        "xtick.major.width": float(PLOT_SETTINGS["axis_width"]),
        "xtick.minor.width": float(PLOT_SETTINGS["axis_width"]),
        "ytick.major.width": float(PLOT_SETTINGS["axis_width"]),
        "ytick.minor.width": float(PLOT_SETTINGS["axis_width"]),
        # 让 PDF/PS 中的文字尽量保持为可编辑 TrueType 字体。
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def configure(settings=None, base_dir=None):
    """根据 JSON settings 更新全局运行参数。

    新版绘图设置位于 settings.plot。旧版 settings.dpi 仍兼容；
    若 settings.plot.dpi 同时存在，则以新版值为准。
    """
    global DATA_DIR, OUT_DIR, LASER_WAVELENGTH_NM, DPI, PLOT_SETTINGS
    global SPACE_UNIT, SPACE_FACTOR, TIME_UNIT, TIME_FACTOR

    settings = settings or {}
    if not isinstance(settings, dict):
        raise TypeError("settings 必须是 JSON object")
    base_dir = Path(base_dir or ".").resolve()

    DATA_DIR = _resolve_path(settings.get("data_dir", "Data"), base_dir)
    out_value = settings.get("out_dir")
    OUT_DIR = (
        _resolve_path(out_value, base_dir)
        if out_value not in (None, "")
        else DATA_DIR / "postprocess"
    )

    LASER_WAVELENGTH_NM = float(settings.get("laser_wavelength_nm", 800.0))
    SPACE_UNIT = str(settings.get("space_unit", "nm"))
    SPACE_FACTOR = float(settings.get("space_factor", 1.0e9))
    TIME_UNIT = str(settings.get("time_unit", "fs"))
    TIME_FACTOR = float(settings.get("time_factor", 1.0e15))

    plot_input = settings.get("plot") or {}
    if not isinstance(plot_input, dict):
        raise TypeError("settings.plot 必须是 JSON object")

    merged_plot = dict(PLOT_DEFAULTS)
    # 兼容旧版 settings.dpi；新版 settings.plot.dpi 优先。
    if "dpi" in settings and "dpi" not in plot_input:
        merged_plot["dpi"] = settings["dpi"]
    merged_plot.update(plot_input)

    merged_plot["format"] = str(merged_plot["format"]).lower().lstrip(".")
    if not merged_plot["format"]:
        raise ValueError("settings.plot.format 不能为空")
    merged_plot["dpi"] = int(merged_plot["dpi"])
    if merged_plot["dpi"] <= 0:
        raise ValueError("settings.plot.dpi 必须 > 0")
    merged_plot["fig_single"] = _validate_pair(
        merged_plot["fig_single"], "settings.plot.fig_single"
    )
    merged_plot["fig_double"] = _validate_pair(
        merged_plot["fig_double"], "settings.plot.fig_double"
    )

    for key in (
        "font_label", "font_tick", "font_legend", "font_panel",
        "font_annotation", "line_width", "axis_width",
    ):
        merged_plot[key] = float(merged_plot[key])
        if merged_plot[key] <= 0:
            raise ValueError(f"settings.plot.{key} 必须 > 0")

    PLOT_SETTINGS = merged_plot
    DPI = int(PLOT_SETTINGS["dpi"])
    _apply_plot_style()
    _update_derived_constants()


def _task_plot_settings(task=None):
    """返回某个 task 的有效绘图设置。"""
    settings = dict(PLOT_SETTINGS)
    if task is not None:
        override = task.get("plot") or {}
        if not isinstance(override, dict):
            raise TypeError(f"task {task.get('name', '<unnamed>')} 的 plot 必须是 JSON object")
        settings.update(override)
    return settings


def _figure_size(task=None):
    """解析 task.plot.figure_size。默认使用论文单栏尺寸。"""
    settings = _task_plot_settings(task)
    spec = settings.get("figure_size", "single")

    if isinstance(spec, str):
        key = spec.lower()
        if key == "single":
            return tuple(_validate_pair(settings["fig_single"], "plot.fig_single"))
        if key == "double":
            return tuple(_validate_pair(settings["fig_double"], "plot.fig_double"))
        raise ValueError('plot.figure_size 字符串只能是 "single" 或 "double"')

    return tuple(_validate_pair(spec, "plot.figure_size"))


def _overview_figure_size(task=None):
    """多 panel 图默认使用双栏尺寸，可由 overview_figure_size 强制覆盖。"""
    settings = _task_plot_settings(task)
    if "overview_figure_size" in settings:
        return tuple(_validate_pair(
            settings["overview_figure_size"], "plot.overview_figure_size"
        ))
    return tuple(_validate_pair(settings["fig_double"], "plot.fig_double"))


def _save_figure(fig, directory, stem, task=None):
    """按全局/task 绘图设置保存静态图并返回实际路径。"""
    settings = _task_plot_settings(task)
    fmt = str(settings.get("format", "png")).lower().lstrip(".")
    if not fmt:
        raise ValueError("plot.format 不能为空")
    dpi = int(settings.get("dpi", PLOT_SETTINGS["dpi"]))
    if dpi <= 0:
        raise ValueError("plot.dpi 必须 > 0")

    path = directory / f"{stem}.{fmt}"
    kwargs = {"dpi": dpi, "format": fmt}
    bbox_inches = settings.get("bbox_inches", "tight")
    if bbox_inches not in (None, ""):
        kwargs["bbox_inches"] = bbox_inches
    fig.savefig(path, **kwargs)
    return path


def _expand_sequence_spec(value, name):
    """展开 JSON 中的函数式序列写法。

    支持：
      {"arange": [start, stop, step]}
      {"linspace": [start, stop, num]}
      {"range": [start, stop, step]}
    """
    if not isinstance(value, dict):
        return value

    if len(value) != 1:
        raise ValueError(f"{name} 的序列对象必须只包含一个键")

    kind, args = next(iter(value.items()))
    if not isinstance(args, list):
        raise TypeError(f"{name}.{kind} 必须是 JSON 数组")

    if kind == "arange":
        if len(args) not in (2, 3):
            raise ValueError(f"{name}.arange 需要 [start, stop] 或 [start, stop, step]")
        return np.arange(*args)
    if kind == "linspace":
        if len(args) != 3:
            raise ValueError(f"{name}.linspace 需要 [start, stop, num]")
        return np.linspace(args[0], args[1], int(args[2]))
    if kind == "range":
        if len(args) not in (2, 3):
            raise ValueError(f"{name}.range 需要 [start, stop] 或 [start, stop, step]")
        return range(*(int(x) for x in args))

    raise ValueError(
        f"{name} 不支持序列类型 {kind!r}；可用 arange、linspace、range"
    )

def open_sdf(path, particle_file=False):
    """粒子任务必须 keep_particles=True。"""
    return sx.open_dataset(path, keep_particles=particle_file)


def close_sdf(ds):
    close = getattr(ds, "close", None)
    if callable(close):
        close()


def get_files(prefix):
    files = sorted(DATA_DIR.glob(f"{prefix}*.sdf"))
    if not files:
        raise FileNotFoundError(f"没有找到 {DATA_DIR / (prefix + '*.sdf')}")
    return files


def get_time_fs(path):
    ds = open_sdf(path)
    time_fs = float(ds.attrs["time"] * TIME_FACTOR)
    close_sdf(ds)
    return time_fs


def _selection_values(value, name):
    """把单值、列表或 JSON 函数式序列统一转换为 Python list。"""
    value = _expand_sequence_spec(value, name)

    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} 不能是字符串")

    if np.isscalar(value):
        return [value]

    try:
        values = list(value)
    except TypeError:
        return [value]

    if not values:
        raise ValueError(f"{name} 不能为空")
    return values


def selection_is_multiple(select):
    """判断 select 是否请求了多个明确时刻/编号。"""
    mode = select.get("mode", "latest")
    if mode == "time":
        return len(_selection_values(select["time_fs"], "time_fs")) > 1
    if mode == "number":
        return len(_selection_values(select["number"], "number")) > 1
    return False


def select_one_file(prefix, select):
    """选择一个 SDF 文件；若传入多个 time/number，则明确报错。"""
    files = get_files(prefix)
    mode = select.get("mode", "latest")

    if mode == "latest":
        path = files[-1]

    elif mode == "number":
        numbers = _selection_values(select["number"], "number")
        if len(numbers) != 1:
            raise ValueError(
                "select_one_file 只能处理一个 number；多个编号请使用多值选择逻辑"
            )
        number = int(numbers[0])
        candidates = []
        for path0 in files:
            suffix = path0.stem[len(prefix):]
            if suffix.isdigit() and int(suffix) == number:
                candidates.append(path0)
        if len(candidates) != 1:
            raise FileNotFoundError(f"找不到唯一的 {prefix}*{number}.sdf")
        path = candidates[0]

    elif mode == "time":
        targets = _selection_values(select["time_fs"], "time_fs")
        if len(targets) != 1:
            raise ValueError(
                "select_one_file 只能处理一个 time_fs；多个时刻请使用多值选择逻辑"
            )
        target = float(targets[0])
        left, right = 0, len(files) - 1
        left_time = get_time_fs(files[left])
        right_time = get_time_fs(files[right])

        if target <= left_time:
            path = files[left]
        elif target >= right_time:
            path = files[right]
        else:
            while right - left > 1:
                middle = (left + right) // 2
                middle_time = get_time_fs(files[middle])
                if middle_time < target:
                    left, left_time = middle, middle_time
                else:
                    right, right_time = middle, middle_time
            path = files[left] if abs(left_time - target) <= abs(right_time - target) else files[right]

    else:
        raise ValueError('select.mode 必须是 "time"、"number" 或 "latest"')

    return path, get_time_fs(path)


def select_files_from_select(prefix, select):
    """根据 select 返回一个或多个指定文件。

    返回
    ----
    mode : str
        "time"、"number" 或 "latest"。
    selected : list[tuple]
        每项为 (requested_value, path, actual_time_fs)。
        time 模式 requested_value 为目标 fs；number 模式为目标文件编号。
    """
    mode = select.get("mode", "latest")

    if mode == "latest":
        path, actual_time = select_one_file(prefix, select)
        return mode, [(None, path, actual_time)]

    if mode == "time":
        values = _selection_values(select["time_fs"], "time_fs")
        selected = []
        for value in values:
            target_time = float(value)
            path, actual_time = select_one_file(
                prefix, {"mode": "time", "time_fs": target_time}
            )
            selected.append((target_time, path, actual_time))
        return mode, selected

    if mode == "number":
        values = _selection_values(select["number"], "number")
        selected = []
        for value in values:
            number = int(value)
            path, actual_time = select_one_file(
                prefix, {"mode": "number", "number": number}
            )
            selected.append((number, path, actual_time))
        return mode, selected

    raise ValueError('select.mode 必须是 "time"、"number" 或 "latest"')


def select_files_at_times(prefix, times_fs):
    """兼容旧接口：为一组目标时刻分别选择最接近的 SDF 文件。"""
    _, selected = select_files_from_select(
        prefix, {"mode": "time", "time_fs": times_fs}
    )
    return selected


def select_many_files(prefix, time_range, stride=1, max_frames=None):
    if stride < 1:
        raise ValueError("stride 必须 >= 1")

    start, end = time_range if time_range is not None else (None, None)
    selected = []

    for path in get_files(prefix)[::stride]:
        time_fs = get_time_fs(path)
        if start is not None and time_fs < start:
            continue
        if end is not None and time_fs > end:
            continue
        selected.append((path, time_fs))

    if not selected:
        raise RuntimeError("指定时间范围内没有 SDF 文件")

    if max_frames is not None and len(selected) > max_frames:
        indices = np.linspace(0, len(selected) - 1, max_frames, dtype=int)
        selected = [selected[i] for i in np.unique(indices)]

    return selected


def find_variable(ds, specification):
    all_names = list(ds.variables)

    if "name" in specification:
        name = specification["name"]
        if name not in ds:
            raise KeyError(f"没有变量 {name}\n可用变量：\n" + "\n".join(all_names))
        return ds[name], name

    words = [word.lower() for word in specification.get("contains", [])]
    matches = [name for name in all_names if all(word in name.lower() for word in words)]

    if len(matches) != 1:
        raise KeyError(
            f"关键词 {specification.get('contains')} 匹配到 {len(matches)} 个变量：\n"
            + "\n".join(matches)
            + "\n\n可用变量：\n"
            + "\n".join(all_names)
        )

    return ds[matches[0]], matches[0]


def inspect_file(inspect):
    path, time_fs = select_one_file(inspect["prefix"], inspect["select"])
    ds = open_sdf(path, inspect.get("particle_file", False))

    print(f"\nfile = {path}")
    print(f"time = {time_fs:.6f} {TIME_UNIT}\n")

    for name in ds.variables:
        da = ds[name]
        print(f"{name}")
        print(f"    dims  = {da.dims}")
        print(f"    shape = {da.shape}")

    close_sdf(ds)


# =============================================================================
# 空间数组处理
# =============================================================================

def axis_dim(da, axis):
    axis = axis.lower()
    matches = [
        dim for dim in da.dims
        if dim.lower() == axis or dim.lower().startswith(axis + "_")
    ]
    if len(matches) != 1:
        raise ValueError(f"无法从 {da.dims} 中唯一识别 {axis} 维")
    return matches[0]


def cut_nearest(da, cuts):
    actual = {}
    for axis, requested in cuts.items():
        dim = axis_dim(da, axis)
        coordinate = np.asarray(da.coords[dim].values) * SPACE_FACTOR
        index = int(np.argmin(np.abs(coordinate - requested)))
        actual[axis] = float(coordinate[index])
        da = da.isel({dim: index})
    return da, actual


def extract_2d(da, axes, cuts, xlim, ylim):
    da, actual = cut_nearest(da, cuts)
    xdim = axis_dim(da, axes[0])
    ydim = axis_dim(da, axes[1])
    # EPOCH sdf_xarray 不适合 lazy mean
    # 对多余维度直接取切片
    for dim in list(da.dims):
        if dim not in (xdim, ydim):
            # 如果该维度长度为1，直接去掉
            if da.sizes[dim] == 1:
                da = da.isel({dim: 0})
            else:
                # 默认取中心切片
                index = da.sizes[dim] // 2
                da = da.isel({dim: index})

    # 关键：
    # 强制 sdf_xarray 在这里完成读取
    da = da.load()
    da = da.transpose(ydim, xdim)
    
    x = np.asarray(
        da.coords[xdim].values
    ) * SPACE_FACTOR

    y = np.asarray(
        da.coords[ydim].values
    ) * SPACE_FACTOR

    values = np.asarray(
        da.values,
        dtype=float
    )

    if xlim is not None:
        mask = (x >= xlim[0]) & (x <= xlim[1])
        x = x[mask]
        values = values[:, mask]

    if ylim is not None:
        mask = (y >= ylim[0]) & (y <= ylim[1])
        y = y[mask]
        values = values[mask, :]
    return x, y, values, actual


def extract_line(da, line_axis, cuts, space_range):

    da, actual = cut_nearest(da, cuts)
    dim = axis_dim(da, line_axis)

    for other_dim in list(da.dims):
        if other_dim != dim:
            if da.sizes[other_dim] == 1:
                da = da.isel({other_dim:0})
            else:
                index = da.sizes[other_dim]//2
                da = da.isel({other_dim:index})

    da = da.load()
    da = da.transpose(dim)
    
    space = np.asarray(
        da.coords[dim].values
    ) * SPACE_FACTOR
    values = np.asarray(
        da.values,
        dtype=float
    )

    if space_range is not None:
        mask = (
            (space >= space_range[0]) &
            (space <= space_range[1])
        )
        space = space[mask]
        values = values[mask]

    return space, values, actual


# =============================================================================
# 粒子数组处理
# =============================================================================

def particle_values(da, specification):
    component = specification.get("component")

    if component is not None:
        component_index = {"x": 0, "y": 1, "z": 2}.get(component, component)
        component_index = int(component_index)
        component_dim = specification.get("component_dim")

        if component_dim is None:
            small_dims = [dim for dim in da.dims if da.sizes[dim] in (2, 3)]
            if len(small_dims) != 1:
                raise ValueError(
                    f"无法识别粒子坐标分量维：dims={da.dims}, shape={da.shape}。"
                    "请设置 component_dim。"
                )
            component_dim = small_dims[0]

        da = da.isel({component_dim: component_index})

    return np.asarray(da.values, dtype=float).reshape(-1)


def read_particles(ds, task, x_key, y_key=None):
    x_da, x_name = find_variable(ds, task[x_key])
    x = particle_values(x_da, task[x_key])

    y = None
    y_name = None
    if y_key is not None:
        y_da, y_name = find_variable(ds, task[y_key])
        y = particle_values(y_da, task[y_key])

    weights = None
    weight_name = None
    if task.get("weight_variable") is not None:
        w_da, weight_name = find_variable(ds, task["weight_variable"])
        weights = particle_values(w_da, task["weight_variable"])

    lengths = [len(x)]
    if y is not None:
        lengths.append(len(y))
    if weights is not None:
        lengths.append(len(weights))
    if len(set(lengths)) != 1:
        raise ValueError(f"粒子变量长度不一致：{lengths}")

    finite = np.isfinite(x)
    if y is not None:
        finite &= np.isfinite(y)
    if weights is not None:
        finite &= np.isfinite(weights)

    x = x[finite]
    y = None if y is None else y[finite]
    weights = None if weights is None else weights[finite]

    return x, y, weights, (x_name, y_name, weight_name)


# =============================================================================
# 归一化和色标
# =============================================================================

def normalize(values, settings):
    settings = settings or {}
    kind = settings.get("kind", "none")

    if kind == "density_nc":
        factor = 1.0 / NC
    elif kind == "current_j0":
        factor = 1.0 / J0
    elif kind == "momentum_mec":
        factor = 1.0 / (m_e * c)
    else:
        factor = float(settings.get("factor", 1.0))

    return np.asarray(values, dtype=float) * factor


def color_norm(values, task):
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("没有可绘制的有限数据")

    scale = task.get("scale", "linear")
    percentile = float(task.get("percentile", 99.5))
    vmin = task.get("vmin")
    vmax = task.get("vmax")

    if scale == "log":
        positive = finite[finite > 0]
        if positive.size == 0:
            raise ValueError("log 色标要求数据中有正值")
        if vmin is None:
            vmin = max(float(np.percentile(positive, 0.5)), 1.0e-30)
        if vmax is None:
            vmax = float(np.percentile(positive, percentile))
        return LogNorm(vmin=vmin, vmax=vmax)

    if scale == "symlog":
        limit = max(float(np.percentile(np.abs(finite), percentile)), 1.0e-30)
        vmin = -limit if vmin is None else vmin
        vmax = limit if vmax is None else vmax
        return SymLogNorm(
            linthresh=float(task.get("linthresh", limit * 1.0e-3)),
            vmin=vmin,
            vmax=vmax,
        )

    if task.get("symmetric", False):
        limit = max(float(np.percentile(np.abs(finite), percentile)), 1.0e-30)
        vmin = -limit if vmin is None else vmin
        vmax = limit if vmax is None else vmax
    else:
        vmin = float(np.percentile(finite, 100 - percentile)) if vmin is None else vmin
        vmax = float(np.percentile(finite, percentile)) if vmax is None else vmax

    return Normalize(vmin=vmin, vmax=vmax)


def add_markers(ax, markers):
    for position in markers or []:
        ax.axvline(position, linewidth=0.8, linestyle="--", alpha=0.8)


def output_directory(task):
    directory = OUT_DIR / task["name"]
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# =============================================================================
# 空间分布：单图或动图
# =============================================================================

def run_spatial(task):
    directory = output_directory(task)
    label = task.get("normalization", {}).get("label", "value")

    if not task.get("animate", False):
        select = task["select"]
        select_mode, selected = select_files_from_select(task["prefix"], select)
        multiple_selection = len(selected) > 1

        if multiple_selection:
            frames = []
            actual_times = []
            requested_values = []
            file_names = []
            actual_cuts = []
            variable_name = None
            x = y = None

            for requested_value, path, time_fs in selected:
                ds = open_sdf(path)
                da, variable_name = find_variable(ds, task["variable"])
                current_x, current_y, values, actual = extract_2d(
                    da, task["axes"], task.get("cuts", {}),
                    task.get("xlim"), task.get("ylim")
                )
                values = normalize(values, task.get("normalization"))

                if x is None:
                    x, y = current_x, current_y
                elif not np.allclose(current_x, x) or not np.allclose(current_y, y):
                    raise RuntimeError(f"{path.name} 的空间网格发生变化")

                frames.append(values)
                requested_values.append(requested_value)
                actual_times.append(time_fs)
                file_names.append(path.name)
                actual_cuts.append(actual)
                close_sdf(ds)

            frames = np.asarray(frames)
            actual_times = np.asarray(actual_times)
            requested_values = np.asarray(requested_values)
            norm = color_norm(frames, task)

            # 每个选择项单独保存一张图。
            for index, values in enumerate(frames):
                fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
                image = ax.pcolormesh(
                    x, y, values, shading="auto",
                    cmap=task.get("cmap", "viridis"), norm=norm
                )
                fig.colorbar(image, ax=ax, label=label)
                ax.set_xlabel(f"{task['axes'][0]} ({SPACE_UNIT})")
                ax.set_ylabel(f"{task['axes'][1]} ({SPACE_UNIT})")
                ax.set_title(
                    f"{task.get('title', task['name'])}, "
                    f"time={actual_times[index]:.2f}fs"
                )
                add_markers(ax, task.get("markers"))

                if select_mode == "time":
                    tag = f"time={actual_times[index]:.2f}fs"
                    request_text = f"time={actual_times[index]:.2f}fs"
                else:
                    tag = (
                        f"number_{int(requested_values[index]):04d}"
                        f"_time={actual_times[index]:.2f}fs"
                    )
                    request_text = (
                        f"number={int(requested_values[index])}, "
                        f"time={actual_times[index]:.2f}fs"
                    )

                figure_path = _save_figure(
                    fig, directory,
                    f"{task['name']}_{tag}",
                    task,
                )
                plt.close(fig)
                print(
                    f"  {request_text} -> {file_names[index]}"
                )

            # 再生成一张统一色标的多选择对比图。
            nplots = len(frames)
            ncols = min(3, nplots)
            nrows = int(np.ceil(nplots / ncols))
            fig, axes = plt.subplots(
                nrows, ncols, figsize=_overview_figure_size(task),
                constrained_layout=True, squeeze=False
            )
            last_image = None
            for index, ax in enumerate(axes.flat):
                if index >= nplots:
                    ax.set_visible(False)
                    continue
                last_image = ax.pcolormesh(
                    x, y, frames[index], shading="auto",
                    cmap=task.get("cmap", "viridis"), norm=norm
                )
                ax.set_xlabel(f"{task['axes'][0]} ({SPACE_UNIT})")
                ax.set_ylabel(f"{task['axes'][1]} ({SPACE_UNIT})")
                if select_mode == "time":
                    ax.set_title(f"time={actual_times[index]:.2f}fs")
                else:
                    ax.set_title(
                        f"number {int(requested_values[index])}\n"
                        f"time={actual_times[index]:.2f}fs"
                    )
                add_markers(ax, task.get("markers"))

            if last_image is not None:
                fig.colorbar(last_image, ax=axes.ravel().tolist(), label=label)
            fig.suptitle(task.get("title", task["name"]))
            overview_path = _save_figure(
                fig, directory, f"{task['name']}_multiple_{select_mode}", task
            )
            plt.close(fig)

            if task.get("save_data", False):
                save_kwargs = dict(
                    x=x, y=y, values=frames,
                    actual_times_fs=actual_times,
                    files=np.asarray(file_names, dtype=object),
                    variable=variable_name,
                    actual_cuts=np.asarray(actual_cuts, dtype=object),
                    selection_mode=select_mode,
                )
                if select_mode == "number":
                    save_kwargs["target_numbers"] = requested_values.astype(int)
                np.savez_compressed(
                    directory / f"{task['name']}_multiple_{select_mode}.npz",
                    **save_kwargs,
                )

            print(f"  多选择对比图 -> {overview_path}")
            return

        path, time_fs = select_one_file(task["prefix"], select)
        ds = open_sdf(path)
        da, variable_name = find_variable(ds, task["variable"])
        x, y, values, actual = extract_2d(
            da, task["axes"], task.get("cuts", {}), task.get("xlim"), task.get("ylim")
        )
        values = normalize(values, task.get("normalization"))

        fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
        image = ax.pcolormesh(
            x, y, values, shading="auto", cmap=task.get("cmap", "viridis"),
            norm=color_norm(values, task)
        )
        fig.colorbar(image, ax=ax, label=label)
        ax.set_xlabel(f"{task['axes'][0]} ({SPACE_UNIT})")
        ax.set_ylabel(f"{task['axes'][1]} ({SPACE_UNIT})")
        ax.set_title(f"{task.get('title', task['name'])}, t={time_fs:.4f} {TIME_UNIT}")
        add_markers(ax, task.get("markers"))

        figure_path = _save_figure(fig, directory, task["name"], task)
        plt.close(fig)

        if task.get("save_data", False):
            np.savez_compressed(
                directory / f"{task['name']}.npz",
                x=x, y=y, values=values, time_fs=time_fs,
                file=path.name, variable=variable_name,
                actual_cuts=np.array(list(actual.items()), dtype=object),
            )

        close_sdf(ds)
        print(f"  {path.name}, t={time_fs:.4f} fs -> {figure_path}")
        return

    selected = select_many_files(
        task["prefix"], task.get("time_range_fs", [None, None]),
        task.get("stride", 1), task.get("max_frames")
    )

    frames, times = [], []
    x = y = None

    for index, (path, time_fs) in enumerate(selected, 1):
        ds = open_sdf(path)
        da, _ = find_variable(ds, task["variable"])
        current_x, current_y, values, _ = extract_2d(
            da, task["axes"], task.get("cuts", {}), task.get("xlim"), task.get("ylim")
        )
        values = normalize(values, task.get("normalization"))

        if x is None:
            x, y = current_x, current_y
        elif not np.allclose(current_x, x) or not np.allclose(current_y, y):
            raise RuntimeError(f"{path.name} 的空间网格发生变化")

        frames.append(values)
        times.append(time_fs)
        close_sdf(ds)
        print(f"  frame {index}/{len(selected)}: {path.name}")

    frames = np.asarray(frames)
    times = np.asarray(times)
    norm = color_norm(frames, task)

    fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
    image = ax.imshow(
        frames[0], origin="lower", aspect="auto", interpolation="nearest",
        extent=[x.min(), x.max(), y.min(), y.max()],
        cmap=task.get("cmap", "viridis"), norm=norm
    )
    fig.colorbar(image, ax=ax, label=label)
    ax.set_xlabel(f"{task['axes'][0]} ({SPACE_UNIT})")
    ax.set_ylabel(f"{task['axes'][1]} ({SPACE_UNIT})")
    add_markers(ax, task.get("markers"))
    title = ax.set_title(f"{task.get('title', task['name'])}, t={times[0]:.4f} fs")

    def update(frame_index):
        image.set_data(frames[frame_index])
        title.set_text(f"{task.get('title', task['name'])}, t={times[frame_index]:.4f} fs")
        return image, title

    animation = FuncAnimation(fig, update, frames=len(frames), blit=False)
    animation_path = directory / f"{task['name']}.gif"
    animation.save(animation_path, writer=PillowWriter(fps=task.get("fps", 12)))
    plt.close(fig)

    if task.get("save_data", False):
        np.savez_compressed(
            directory / f"{task['name']}.npz",
            x=x, y=y, values=frames, times_fs=times,
        )

    print(f"  animation -> {animation_path}")


# =============================================================================
# 空间-时间图
# =============================================================================

def run_xt(task):
    selected = select_many_files(
        task["prefix"], task.get("time_range_fs", [None, None]),
        task.get("stride", 1), task.get("max_frames")
    )

    rows, times, files = [], [], []
    space = None
    actual = None
    variable_name = None

    for index, (path, time_fs) in enumerate(selected, 1):
        ds = open_sdf(path)
        da, current_name = find_variable(ds, task["variable"])
        current_space, values, current_actual = extract_line(
            da, task["line_axis"], task.get("cuts", {}), task.get("space_range")
        )
        values = normalize(values, task.get("normalization"))

        if space is None:
            space = current_space
            actual = current_actual
            variable_name = current_name
        elif not np.allclose(current_space, space):
            raise RuntimeError(f"{path.name} 的空间网格发生变化")

        rows.append(values)
        times.append(time_fs)
        files.append(path.name)
        close_sdf(ds)

        if index == 1 or index % 20 == 0 or index == len(selected):
            print(f"  file {index}/{len(selected)}: {path.name}")

    values = np.asarray(rows)
    times = np.asarray(times)
    order = np.argsort(times)
    values, times = values[order], times[order]
    files = np.asarray(files)[order]

    directory = output_directory(task)
    fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
    image = ax.pcolormesh(
        space, times, values, shading="auto",
        cmap=task.get("cmap", "viridis"), norm=color_norm(values, task)
    )
    fig.colorbar(
        image, ax=ax,
        label=task.get("normalization", {}).get("label", "value")
    )
    ax.set_xlabel(f"{task['line_axis']} ({SPACE_UNIT})")
    ax.set_ylabel(f"t ({TIME_UNIT})")
    ax.set_title(task.get("title", task["name"]))
    add_markers(ax, task.get("markers"))

    figure_path = _save_figure(fig, directory, task["name"], task)
    plt.close(fig)

    if task.get("save_data", False):
        np.savez_compressed(
            directory / f"{task['name']}.npz",
            space=space, times_fs=times, values=values, files=files,
            variable=variable_name,
            actual_cuts=np.array(list(actual.items()), dtype=object),
        )

    print(f"  x-t figure -> {figure_path}")


# =============================================================================
# 粒子相空间：单图或动图
# =============================================================================

def phase_histogram(x, y, weights, task):
    xlim = task.get("xlim") or [np.percentile(x, 0.1), np.percentile(x, 99.9)]
    ylim = task.get("ylim") or [np.percentile(y, 0.1), np.percentile(y, 99.9)]
    histogram, x_edges, y_edges = np.histogram2d(
        x, y, bins=task.get("bins", [300, 300]),
        range=[xlim, ylim], weights=weights
    )
    return histogram.T, x_edges, y_edges


def run_particle_phase(task):
    directory = output_directory(task)
    x_label = task.get("x_normalization", {}).get("label", "x")
    y_label = task.get("y_normalization", {}).get("label", "y")

    if not task.get("animate", False):
        select_mode, selected_snapshots = select_files_from_select(
            task["prefix"], task["select"]
        )

        if len(selected_snapshots) == 1:
            _, path, time_fs = selected_snapshots[0]
            ds = open_sdf(path, particle_file=True)
            x, y, weights, names = read_particles(ds, task, "x_variable", "y_variable")
            x = normalize(x, task.get("x_normalization"))
            y = normalize(y, task.get("y_normalization"))
            histogram, x_edges, y_edges = phase_histogram(x, y, weights, task)

            fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
            image = ax.pcolormesh(
                x_edges, y_edges, histogram, shading="auto",
                cmap=task.get("cmap", "viridis"), norm=color_norm(histogram, task)
            )
            fig.colorbar(image, ax=ax, label=task.get("color_label", "particle count"))
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.set_title(f"{task.get('title', task['name'])}, t={time_fs:.4f} fs")

            figure_path = _save_figure(fig, directory, task["name"], task)
            plt.close(fig)

            if task.get("save_data", False):
                np.savez_compressed(
                    directory / f"{task['name']}.npz",
                    histogram=histogram, x_edges=x_edges, y_edges=y_edges,
                    time_fs=time_fs, variables=np.array(names, dtype=object),
                )

            close_sdf(ds)
            print(f"  particle phase -> {figure_path}")
            return

        histograms = []
        requested_values = []
        actual_times = []
        file_names = []
        variable_names = None
        x_edges = y_edges = None
        fixed_task = dict(task)

        for requested_value, path, time_fs in selected_snapshots:
            ds = open_sdf(path, particle_file=True)
            x, y, weights, names = read_particles(ds, task, "x_variable", "y_variable")
            x = normalize(x, task.get("x_normalization"))
            y = normalize(y, task.get("y_normalization"))

            if x_edges is None:
                histogram, x_edges, y_edges = phase_histogram(x, y, weights, fixed_task)
                fixed_task["xlim"] = [x_edges[0], x_edges[-1]]
                fixed_task["ylim"] = [y_edges[0], y_edges[-1]]
                variable_names = names
            else:
                histogram, _, _ = phase_histogram(x, y, weights, fixed_task)

            histograms.append(histogram)
            requested_values.append(requested_value)
            actual_times.append(time_fs)
            file_names.append(path.name)
            close_sdf(ds)

        histograms = np.asarray(histograms)
        requested_values = np.asarray(requested_values)
        actual_times = np.asarray(actual_times)
        norm = color_norm(histograms, task)

        for index, histogram in enumerate(histograms):
            fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
            image = ax.pcolormesh(
                x_edges, y_edges, histogram, shading="auto",
                cmap=task.get("cmap", "viridis"), norm=norm
            )
            fig.colorbar(image, ax=ax, label=task.get("color_label", "particle count"))
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.set_title(
                f"{task.get('title', task['name'])}, "
                f"time={actual_times[index]:.2f}fs"
            )

            if select_mode == "time":
                tag = f"time={actual_times[index]:.2f}fs"
                request_text = f"time={actual_times[index]:.2f}fs"
            else:
                tag = (
                    f"number_{int(requested_values[index]):04d}"
                    f"_time={actual_times[index]:.2f}fs"
                )
                request_text = (
                    f"number={int(requested_values[index])}, "
                    f"time={actual_times[index]:.2f}fs"
                )

            figure_path = _save_figure(
                fig, directory,
                f"{task['name']}_{tag}",
                task,
            )
            plt.close(fig)
            print(
                f"  {request_text} -> {file_names[index]}"
            )

        nplots = len(histograms)
        ncols = min(3, nplots)
        nrows = int(np.ceil(nplots / ncols))
        fig, axes = plt.subplots(
            nrows, ncols, figsize=_overview_figure_size(task),
            constrained_layout=True, squeeze=False
        )
        last_image = None
        for index, ax in enumerate(axes.flat):
            if index >= nplots:
                ax.set_visible(False)
                continue
            last_image = ax.pcolormesh(
                x_edges, y_edges, histograms[index], shading="auto",
                cmap=task.get("cmap", "viridis"), norm=norm
            )
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            if select_mode == "time":
                ax.set_title(f"time={actual_times[index]:.2f}fs")
            else:
                ax.set_title(
                    f"number {int(requested_values[index])}\n"
                    f"time={actual_times[index]:.2f}fs"
                )

        if last_image is not None:
            fig.colorbar(
                last_image, ax=axes.ravel().tolist(),
                label=task.get("color_label", "particle count")
            )
        fig.suptitle(task.get("title", task["name"]))
        overview_path = _save_figure(
            fig, directory, f"{task['name']}_multiple_{select_mode}", task
        )
        plt.close(fig)

        if task.get("save_data", False):
            save_kwargs = dict(
                histograms=histograms,
                x_edges=x_edges,
                y_edges=y_edges,
                actual_times_fs=actual_times,
                files=np.asarray(file_names, dtype=object),
                variables=np.asarray(variable_names, dtype=object),
                selection_mode=select_mode,
            )
            if select_mode == "number":
                save_kwargs["target_numbers"] = requested_values.astype(int)
            np.savez_compressed(
                directory / f"{task['name']}_multiple_{select_mode}.npz",
                **save_kwargs,
            )

        print(f"  多选择粒子相空间对比图 -> {overview_path}")
        return

    selected = select_many_files(
        task["prefix"], task.get("time_range_fs", [None, None]),
        task.get("stride", 1), task.get("max_frames")
    )

    histograms, times = [], []
    x_edges = y_edges = None
    fixed_task = dict(task)

    for index, (path, time_fs) in enumerate(selected, 1):
        ds = open_sdf(path, particle_file=True)
        x, y, weights, _ = read_particles(ds, task, "x_variable", "y_variable")
        x = normalize(x, task.get("x_normalization"))
        y = normalize(y, task.get("y_normalization"))

        if x_edges is None:
            histogram, x_edges, y_edges = phase_histogram(x, y, weights, fixed_task)
            fixed_task["xlim"] = [x_edges[0], x_edges[-1]]
            fixed_task["ylim"] = [y_edges[0], y_edges[-1]]
        else:
            histogram, _, _ = phase_histogram(x, y, weights, fixed_task)

        histograms.append(histogram)
        times.append(time_fs)
        close_sdf(ds)
        print(f"  frame {index}/{len(selected)}: {path.name}")

    histograms = np.asarray(histograms)
    times = np.asarray(times)
    norm = color_norm(histograms, task)

    fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
    image = ax.imshow(
        histograms[0], origin="lower", aspect="auto", interpolation="nearest",
        extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]],
        cmap=task.get("cmap", "viridis"), norm=norm
    )
    fig.colorbar(image, ax=ax, label=task.get("color_label", "particle count"))
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    title = ax.set_title(f"{task.get('title', task['name'])}, t={times[0]:.4f} fs")

    def update(frame_index):
        image.set_data(histograms[frame_index])
        title.set_text(f"{task.get('title', task['name'])}, t={times[frame_index]:.4f} fs")
        return image, title

    animation = FuncAnimation(fig, update, frames=len(histograms), blit=False)
    animation_path = directory / f"{task['name']}.gif"
    animation.save(animation_path, writer=PillowWriter(fps=task.get("fps", 12)))
    plt.close(fig)

    if task.get("save_data", False):
        np.savez_compressed(
            directory / f"{task['name']}.npz",
            histograms=histograms, x_edges=x_edges, y_edges=y_edges, times_fs=times,
        )

    print(f"  particle animation -> {animation_path}")


# =============================================================================
# 粒子位置-时间图
# =============================================================================

def run_particle_xt(task):
    selected = select_many_files(
        task["prefix"], task.get("time_range_fs", [None, None]),
        task.get("stride", 1), task.get("max_frames")
    )

    rows, times, files = [], [], []
    edges = None
    space_range = task.get("space_range")

    for index, (path, time_fs) in enumerate(selected, 1):
        ds = open_sdf(path, particle_file=True)
        position, _, weights, _ = read_particles(ds, task, "position_variable")
        position = normalize(position, task.get("position_normalization"))

        if edges is None:
            if space_range is None:
                space_range = [np.percentile(position, 0.1), np.percentile(position, 99.9)]
            edges = np.linspace(space_range[0], space_range[1], task.get("bins", 500) + 1)

        histogram, _ = np.histogram(position, bins=edges, weights=weights)
        rows.append(histogram)
        times.append(time_fs)
        files.append(path.name)
        close_sdf(ds)

        if index == 1 or index % 20 == 0 or index == len(selected):
            print(f"  file {index}/{len(selected)}: {path.name}")

    values = np.asarray(rows)
    times = np.asarray(times)
    order = np.argsort(times)
    values, times = values[order], times[order]
    files = np.asarray(files)[order]
    centers = 0.5 * (edges[:-1] + edges[1:])

    directory = output_directory(task)
    fig, ax = plt.subplots(figsize=_figure_size(task), constrained_layout=True)
    image = ax.pcolormesh(
        centers, times, values, shading="auto",
        cmap=task.get("cmap", "viridis"), norm=color_norm(values, task)
    )
    fig.colorbar(image, ax=ax, label=task.get("color_label", "particle count"))
    ax.set_xlabel(task.get("position_normalization", {}).get("label", "position"))
    ax.set_ylabel(f"t ({TIME_UNIT})")
    ax.set_title(task.get("title", task["name"]))

    figure_path = _save_figure(fig, directory, task["name"], task)
    plt.close(fig)

    if task.get("save_data", False):
        np.savez_compressed(
            directory / f"{task['name']}.npz",
            space_centers=centers, space_edges=edges,
            times_fs=times, values=values, files=files,
        )

    print(f"  particle x-t figure -> {figure_path}")


# =============================================================================
# JSON 配置入口
# =============================================================================

def load_config(config_path):
    config_path = Path(config_path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise TypeError("配置文件顶层必须是 JSON object")
    return config_path, config


def run_config(config_path="epochpost_input.json"):
    config_path, config = load_config(config_path)
    configure(config.get("settings"), config_path.parent)

    inspect = config.get("inspect", {"enabled": False})
    tasks = config.get("tasks", [])

    print("=" * 72)
    print("epochpost - EPOCH PIC post-processing with sdf_xarray")
    print(f"CONFIG   = {config_path}")
    print(f"DATA_DIR = {DATA_DIR}")
    print(f"OUT_DIR  = {OUT_DIR}")
    print(
        "PLOT     = "
        f"{PLOT_SETTINGS['format']}, {PLOT_SETTINGS['dpi']} dpi, "
        f"single={PLOT_SETTINGS['fig_single']} in, "
        f"double={PLOT_SETTINGS['fig_double']} in"
    )
    print(f"nc       = {NC:.6e} m^-3")
    print("=" * 72)

    if not DATA_DIR.is_dir():
        raise FileNotFoundError(f"DATA_DIR 不存在：{DATA_DIR}")

    if inspect.get("enabled", False):
        inspect_file(inspect)
        return

    enabled_tasks = [task for task in tasks if task.get("enabled", True)]
    if not enabled_tasks:
        print("没有启用任务。请在 epochpost_input.json 的 tasks 中加入任务，或将 enabled 设为 true。")
        return

    runners = {
        "spatial": run_spatial,
        "xt": run_xt,
        "particle_phase": run_particle_phase,
        "particle_xt": run_particle_xt,
    }

    for index, task in enumerate(enabled_tasks, 1):
        task_type = task.get("type")
        task_name = task.get("name", f"task_{index:02d}")
        print(f"\n[{index}/{len(enabled_tasks)}] {task_name} ({task_type})")
        if task_type not in runners:
            raise ValueError(f"未知任务类型：{task_type}")
        task.setdefault("name", task_name)
        runners[task_type](task)

    print("\n全部任务完成。")


def _default_config_path():
    primary = Path("epochpost_input.json")
    if primary.is_file():
        return primary
    for legacy_name in ("post_input.json", "input.json"):
        legacy = Path(legacy_name)
        if legacy.is_file():
            return legacy
    raise FileNotFoundError(
        "当前目录没有 epochpost_input.json。请指定配置文件："
        " python new.py path/to/epochpost_input.json"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="EPOCH PIC post-processing driven by a JSON input file"
    )
    parser.add_argument(
        "config", nargs="?", help="配置文件路径；默认查找 ./epochpost_input.json"
    )
    args = parser.parse_args(argv)
    run_config(args.config or _default_config_path())


if __name__ == "__main__":
    main()
