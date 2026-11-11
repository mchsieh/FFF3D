# FFF3D — finite-fault inversion with 3-D strain Green's tensors

Web pages for FFF3D, finite-fault inversion with strain Green's tensors (SGTs) computed in a 3-D velocity model, shown on a **pure synthetic** test: the fault, its slip and the "observed" waveforms are all computed for the test; only the Taiwan 3-D velocity model is real. Waveforms for a hypothetical Mw 6.5 thrust are computed with a 3-D finite-difference code and inverted with SGTs computed in the same model.

## Pages

| Page | URL | Access |
|---|---|---|
| Result report, public summary | https://mchsieh.github.io/FFF3D/ | open |
| Result report, full version (all verification tests, discussion version) | https://mchsieh.github.io/FFF3D/full/ | passphrase |
| Step-by-step walkthrough (running every program of the example) | https://mchsieh.github.io/FFF3D/walkthrough/ | passphrase |

The two protected pages are for the project group (students, assistants, collaborators). They are stored here only as AES-256 ciphertext and are decrypted in the browser with a passphrase obtained from the author; the passphrase is not in this repository. Open the public page from either protected page with the "Public summary" link; the two protected pages link to each other without asking again in the same browser session.

The 3-D SGT inversion is the method of Hsieh, Zhao, Ji & Ma (2016), *Seismological Research Letters* 87(6), 1342–1354, https://doi.org/10.1785/0220160050, built on the FFF code of Ji, Wald & Helmberger (2002), *BSSA* 92(4), 1192–1207. The code itself is **not** in this repository; it is distributed by the authors on request.

## Layout

```
docs/                     the published site (GitHub Pages, branch main, folder /docs)
  index.html fig/ media/  public summary, plain files (media/ holds the two animations, shared by all pages)
  full/index.html         full report, encrypted (figures inside the ciphertext, animations from ../media/)
  walkthrough/index.html  walkthrough, encrypted the same way
  */.sha256               sha256 of the plaintext; the page is re-encrypted only when it changes
build.py                  builds every page from the author's page sources (one source per page; the report source
                          carries data-v="full" / data-v="public" marks that select the two report versions)
protected_loader.html     the small page that asks for the passphrase and decrypts (Web Crypto, PBKDF2 + AES-CBC)
LICENSE                   CC BY 4.0 for the public page (text and figures)
```

Building needs the author's project directory and the passphrase file next to this repository (`../FFF3D.passphrase`, never committed); `python3 build.py` writes `docs/` and the three self-contained copies used on claude.ai.

## Citation

If you use these pages, please cite Hsieh et al. (2016) for the method.

## License

The public page (text, figures and animations): [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) (see `LICENSE`). The protected pages are for the project group and are not licensed for redistribution.
