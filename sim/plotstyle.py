"""Shared matplotlib style for the result plots."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
# categorical slots in fixed order
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "font.size": 9.5,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.labelcolor": INK2,
    "axes.titlecolor": INK,
    "axes.titlesize": 10.5,
    "axes.titleweight": "semibold",
    "axes.titlelocation": "left",
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.7,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK2,
    "ytick.labelcolor": INK2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "lines.linewidth": 1.6,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
    "legend.frameon": False,
    "legend.fontsize": 8.8,
    "legend.labelcolor": INK2,
    "figure.dpi": 110,
    "savefig.dpi": 160,
})


def limit_line(ax, y, text, horizontal=True, where=0.99):
    """Thin dashed line for a target limit, labelled in secondary ink."""
    if horizontal:
        ax.axhline(y, color=MUTED, lw=0.9, ls=(0, (4, 3)), zorder=1)
        ax.annotate(text, xy=(where, y), xycoords=("axes fraction", "data"),
                    ha="right", va="bottom", color=INK2, fontsize=8.3)
    else:
        ax.axvline(y, color=MUTED, lw=0.9, ls=(0, (4, 3)), zorder=1)
        ax.annotate(text, xy=(y, where), xycoords=("data", "axes fraction"),
                    ha="left", va="top", color=INK2, fontsize=8.3, rotation=90)


def note(ax, x, y, text, ha="left", va="center", coords="data"):
    ax.annotate(text, xy=(x, y), xycoords=coords, ha=ha, va=va, color=INK2, fontsize=8.3)


def save(fig, path):
    fig.savefig(path, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
