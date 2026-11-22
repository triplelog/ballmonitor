Inline Math Greek (inlinemath-greek-regular.woff2, inlinemath-greek-italic.woff2)

The Greek letters that maths uses (Α–Ω, α–ω and ϑ ϕ ϖ ϰ ϱ ϴ ϵ), cut from New Computer Modern 8.1.1
by Antonis Tsolomitis (CTAN: fonts/newcomputermodern):

  inlinemath-greek-regular.woff2   from NewCM10-Book.otf
  inlinemath-greek-italic.woff2    from NewCM10-Italic.otf

Both source fonts are under the GUST Font License (GUST-FONT-LICENSE.txt in this folder), which asks
that derived fonts carry new names: these are named "Inline Math Greek" inside the files and in their
file names. Nothing was changed but the letters kept, the kerning between them, and the names.
tools/make-greek-font.py makes them again from the source fonts.

fonts.css declares them as part of "Inline Math Roman" for the Greek letters only (unicode-range), so a
page downloads them only when it shows Greek.
