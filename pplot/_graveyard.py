#
#
# def plot_lab_spectra(ax, minerals=[]):
#     # Define the right axis for the lab data labels
#     pry = ax.twinx()
#     despine(pry)  # remove the bounding box
#     pry.set_yticks([])  # wipe auto-ticks or they stick around
#     pry.set_ylim(ax.get_ylim())
#
#     # Plot the requested lab spectra
#     s = {}
#     _ = [s.update(lab_spectra[k]) for k in lab_spectra.keys()]
#     ticks, labels = [], []
#     for i, m in enumerate(minerals):
#         data = pd.read_csv(
#             s[m], skiprows=17
#         )  # pd.read_csv(s[m],names=['Wavelength','Response'])
#         data_inplot = data.loc[data["Wavelength"] >= pry.get_xlim()[0]].loc[
#             data["Wavelength"] < pry.get_xlim()[1]
#         ]
#         ylim = (pry.get_ylim()[0] + 0.1, ax.get_ylim()[1] - 0.1)
#         data_scaled = (
#             data_inplot["Response"] - np.min(data_inplot["Response"])
#         ) * np.diff(ylim) / (
#             np.max(data_inplot["Response"]) - np.min(data_inplot["Response"])
#         ) + ylim[
#             0
#         ]
#         pry.plot(
#             data_inplot["Wavelength"],
#             # data_scaled,
#             data_inplot["Response"],
#             "k",
#             alpha=0.7,
#             linewidth=2,
#         )
#         ticks += [data_inplot["Response"].values[-1]]
#         labels += [m.replace(" ", "\n")]
#     pry.set_yticks(ticks)
#     pry.set_yticklabels(labels, fontproperties=legend_fp)
#
