# Bundled India geography

`frontend/src/data/india-geography.json` contains the application’s offline state, Union Territory and district list. It was retrieved from the Ministry of Panchayati Raj’s Local Government Directory (LGD) state and district list services on **2026-11-06**. The snapshot contains 28 states, 8 Union Territories and 790 LGD-coded districts. Each district is nested under its LGD state and also carries that state’s code.

Source: [Local Government Directory](https://lgdirectory.gov.in/). The app does not call LGD at runtime. English names and LGD codes are canonical; requests send canonical English names to preserve current backend contracts.

English, Telugu, Hindi, Tamil, Kannada, Malayalam and Marathi labels are present for every state, Union Territory and district in this snapshot. LGD local names are used when a name is provided in the relevant script. Otherwise, the bundled labels use macOS ICU transliteration of the English proper name. This keeps names recognizable without a translation service or extra runtime package. It is transliteration, not a semantic translation. Automated transliterations need review by fluent speakers; common pilot names have manually curated spellings. This snapshot currently has **zero English fallbacks**. Records expose `fallbackLanguages` so a future update can record any English fallback per name.

The optional refresh script is `scripts/generate_india_geography.py`. It fetches the official public LGD services and uses the macOS Swift/Foundation ICU transliterator; the generated JSON is checked into the frontend and is the only data used at runtime.
