# matplotlib/seaborn → Plotly mapping + traps

Constructs first, then the silent-behavior traps that shift numbers or drop data during translation.

## Construct map

| Notebook construct | Plotly equivalent | Notes |
|---|---|---|
| `ax.plot(x, y)` | `go.Scatter(mode="lines")` | |
| `ax.twinx()` | `make_subplots(specs=[[{"secondary_y": True}]])` + `secondary_y=True` per trace | axis ranges no longer auto-shared |
| `plt.subplots(r, c)` | `make_subplots(rows, cols)` — or the host app's grid factory (per-subplot legends) | |
| `ax.bar` / stacked | `go.Bar` + `barmode="stack"\|"group"\|"overlay"` | mpl stacks via bottom=; plotly via barmode |
| `ax.fill_between` | two `go.Scatter` traces + `fill="tonexty"` | order matters: lower trace first |
| `ax.axhline/axvline` | `fig.add_hline/add_vline` | |
| `ax.set_yscale("log")` | `yaxis_type="log"` | log axes change perceived story — never drop |
| `plt.imshow` / `sns.heatmap` | `go.Heatmap` | mpl y-origin is TOP for imshow; plotly heatmap y ascends — `yaxis autorange="reversed"` to match |
| `sns.heatmap(annot=True)` | `go.Heatmap(text=..., texttemplate="%{text}")` | |
| `sns.lineplot(hue=...)` | one trace per group (groupby loop) | see estimator trap below |
| `sns.scatterplot(hue/size=...)` | `go.Scatter` per group, or `marker.size` array | |
| `sns.barplot` | `go.Bar` on PRE-AGGREGATED data | barplot aggregates internally — see trap |
| `sns.histplot` / `plt.hist` | `go.Histogram` | bin algorithms differ — pass explicit bins to both or precompute with np.histogram |
| `sns.kdeplot` | precompute with `scipy.stats.gaussian_kde` → `go.Scatter` | plotly has no native KDE |
| `sns.regplot` | scatter + manual `np.polyfit` line trace | compute the fit in the compute layer, parity-check the coefficients |
| `sns.boxplot/violinplot` | `go.Box` / `go.Violin` | whisker definitions differ (see trap) |
| `pd.DataFrame.plot(...)` | iterate columns → traces | `.plot()` hides a loop; make it explicit |
| color=`C0`,`tab10`, sns palettes | host app's palette (`palette.qualitative`) | never hardcode hex; theme via the app's template |
| `plt.xticks(rotation=45)` | `xaxis_tickangle=-45` | |
| dates on x (mpl auto-locator) | plotly handles natively | rangebreaks if the notebook hid weekends |

## Traps that change numbers or drop data

1. **mpl silently drops NaN in line plots** (gap in the line); Plotly also gaps by default (`connectgaps=False`) — but if the port added `.dropna()` to "clean up", the x-alignment between traces changed. Parity on arrays catches it.
2. **seaborn AGGREGATES inside the plot call.** `sns.lineplot`/`barplot` with repeated x values compute mean + 95% CI bootstrap by default. The notebook's line is NOT the raw data. Either reproduce (groupby mean in the compute layer + optional CI band) or consciously drop the CI with a ledger entry. Bootstrap CIs are UNSEEDED by default (`seed=None`) — the band differs on every run, so exact equality is impossible; pass `seed=`/`n_boot` when reproducing in the compute layer, else compare the band with tolerance and ledger it.
3. **Histogram bins:** mpl default 10 bins; plotly auto-bins differently; seaborn uses its own rules. Precompute `np.histogram` in the compute layer and hand both notebook and page the same bins, or pass explicit `bins=`/`xbins`.
4. **Box/violin internals:** whisker rule (1.5*IQR variants), outlier display, and KDE bandwidth differ across libs. If the notebook's exact quartiles matter, compute them in the compute layer and annotate.
5. **imshow orientation:** top-left origin vs plotly's bottom-left — a heatmap that "looks transposed/flipped" after port is this, not the data.
6. **twinx ranges:** mpl auto-scales each y independently around its data; after porting, plotly does too, but if the notebook manually set ylim on one axis, matching visuals requires porting those limits.
7. **Category order:** mpl/seaborn use appearance order or category dtype order; plotly sorts differently — pass `category_orders`/explicit tick arrays when the notebook's ordering carried meaning.
8. **`.plot()` sharex/stacked area defaults** (`df.plot.area` stacks by default) — verify stacking intent, don't assume.
9. **Date index frequency:** notebook may rely on matplotlib skipping missing dates visually while plotly draws a continuous time axis (weekend flatlines). `rangebreaks` or business-day reindex decision — ledger it.
10. **Colormaps for diverging data:** `sns.heatmap(cmap="RdBu_r")` does NOT center at 0 by default — it anchors to data min/max; centering only happens when the notebook passed `center=0`. Mirror that: `center=0` in the notebook → `zmid=0` in the plotly heatmap; no `center=` → do NOT add `zmid=0` (it would change the visual story in the name of fidelity).
