fonts — ship these with the kit
===============================

Every plate's typeRoles names one of two families and nothing else. They are
here as real font files because a manifest that names a font it does not ship
is a manifest that renders wrong silently: the renderer substitutes, every
plate is subtly off, and nobody notices until a video is out.

  Archivo Narrow    titles, kickers, labels, period headers.
                    ArchivoNarrow[wght].ttf is a VARIABLE font covering the
                    whole 400-700 axis, which is every weight the typeRoles
                    reference (400 / 500 / 600 / 700). Italic ships too,
                    unused at present — do not introduce it without a reason.

  Courier Prime     figures, units, tickers, annotation captions. Static files,
                    one per weight. 400 and 700 are both referenced: 700 is the
                    last-column weight on every numbers sheet. Italic and
                    BoldItalic ship unused.

WEIGHTS REFERENCED BY typeRoles, AND THE FILE THAT SERVES EACH

  Archivo Narrow 400, 500, 600, 700   ArchivoNarrow[wght].ttf (variable)
  Courier Prime 400                   CourierPrime-Regular.ttf
  Courier Prime 700                   CourierPrime-Bold.ttf

If a renderer cannot do variable fonts, instance ArchivoNarrow[wght].ttf at
400/500/600/700 and keep the family name. Do not substitute a different narrow
grotesque: the label and figure maxChars in every typeRoles table were measured
against THIS face, and a wider one overflows cells the manifest promises fit.

LICENCES
  Both families are under the SIL Open Font License 1.1. The licences ship
  beside them (ArchivoNarrow-OFL.txt, CourierPrime-OFL.txt) and must travel
  with any copy of this kit. Source: github.com/google/fonts.

This applies to every future batch: a family that names a new face ships the
face, in this folder, with its licence.
