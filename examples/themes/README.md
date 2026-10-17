# Example themes

`sunset.ctheme.d/` is a theme **bundle** folder: `theme.json` (colours, plus a vector `chart`
icon and the default wallpaper), `wallpapers/dusk.webp` and `icons/wallet.png`. Turn it into a
file you can upload in Settings → Appearance:

```bash
crypto-helper theme check examples/themes/sunset.ctheme.d     # same checks as the server
crypto-helper theme pack examples/themes/sunset.ctheme.d      # -> examples/themes/sunset.ctheme
```

The format is described in WIKI/reference/themes.md.
