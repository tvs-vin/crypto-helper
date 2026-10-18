# xterm.js (vendored)

The terminal emulator used by the Terminal window. MIT licensed (LICENSE.txt).

| File | Package | Version | npm integrity (checked when vendored) |
|---|---|---|---|
| xterm.js, xterm.css | @xterm/xterm | 5.5.0 | sha512-hqJHYaQb5OptNunnyAnkHyM8aCjZ1MEIDTQu1iIbbTD/xops91NB5yq1ZK/dC2JDbVWtF23zUtl9JE2NqwT87A== |
| addon-canvas.js | @xterm/addon-canvas | 0.7.0 | sha512-LF5LYcfvefJuJ7QotNRdRSPc9YASAVDeoT5uyXS/nZshZXjYplGXRECBGiznwvhNL2I8bq1Lf5MzRwstsYQ2Iw== |
| addon-fit.js | @xterm/addon-fit | 0.10.0 | sha512-UFYkDm4HUahf2lnEyHvio51TNGiLK66mqP2JoATy7hRZeXaGMRDr00JiSF7m63vR5WKATF605yEggJKsw0JpMQ== |

The canvas renderer is loaded **before** the terminal opens, so xterm never creates its DOM
renderer (which injects `<style>` elements that the strict Content-Security-Policy blocks).
Source maps were left out. Upgrading: replace the files, update this table, and run the
Terminal browser test.
