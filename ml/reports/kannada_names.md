# How good are the AI-spelled Kannada village names?

Gemini (gemini-3.8-flash, without local examples) was asked, with the same prompt as for real, for 300 randomly chosen villages that already have a Kannada name in OpenStreetMap. The mappers' spelling is the reference (it can have mistakes too, and some villages have two accepted spellings).

| Measure | Result |
|---|---|
| Same letters as OpenStreetMap (ignoring spaces, dots, dashes) | **51%** |
| Exactly identical | 49% |
| Passed our automatic "sounds like the census name" check | 100% |
| Of those that passed, same letters as OpenStreetMap | 51% |
| Refused by the check although they were right | 0 |

The check catches answers that are a different word; it cannot catch small spelling differences (ಳ vs ಲ, long vs short vowels), which is what most of the remaining differences are. That is why AI names are marked "(AI)" on the dashboard and can be corrected in ml/data/name_kn_fixes.csv.

## Differences (first 25)

| Census name | Taluk | OpenStreetMap | AI | Passed check |
|---|---|---|---|---|
| Nagaral | Bagalkot | ನಾಯನೇಗಲಿ | ನಾಗರಾಳ | yes |
| Galgali | Bilgi | ಗಲಗಲಿ | ಗಳಗಲಿ | yes |
| Chinchakhandi B K | Mudhol | ಚಿಂಚಖಂಡಿ | ಚಿಂಚಖಂಡಿ ಬಿ ಕೆ | yes |
| Siddapur | Sandur | ಸಿದ್ದಾಪುರ | ಸಿದ್ಧಾಪುರ | yes |
| Talur | Sandur | ತಾಳೂರು | ತಾಲೂರು | yes |
| Vattumuruvani | Siruguppa | ವತ್ತುಮುರುವಣಿ | ವಟ್ಟುಮುರುವಾನಿ | yes |
| Ittigihal | Siruguppa | ಇಟ್ಟಿಗಿಹಾಳು | ಇಟ್ಟಿಗಿಹಾಳ್ | yes |
| Marigeri | Bailhongal | ಮರಿಗೇರಿ | ಮಾರಿಗೇರಿ | yes |
| Shamanewadi | Chikodi | ಶಮನೆವಾಡಿ | ಶಮಾನೇವಾಡಿ | yes |
| Padlihal | Chikodi | ಪಡಲಿಹಾಳ | ಪಡ್ಲಿಹಾಳ | yes |
| Budihal | Gokak | ಬೂದಿಹಾಳ | ಬುದಿಹಾಳ | yes |
| Chickamanoli | Khanapur | ಚಿಕ್ಕಮುನವಳ್ಳಿ | ಚಿಕ್ಕಮನೋಳಿ | yes |
| Kalmani | Khanapur | ಕಾಲಮನಿ | ಕಲಮನಿ | yes |
| Mellikeri | Saundatti | ಮನ್ನಿಕೇರಿ | ಮೆಳ್ಳಿಕೇರಿ | yes |
| Katamalli | Saundatti | ಕಟಮಳ್ಳಿ | ಕಾಟಮಳ್ಳಿ | yes |
| Boodihal | Devanahalli | ಬೂದಿಹಾಳ | ಬೂದಿಹಾಳ್ | yes |
| Nagarabavi Layout Og | Bengaluru North | ನಾಗರಭಾವಿ | ನಾಗರಭಾವಿ ಬಡಾವಣೆ | yes |
| Suradenpura | Bengaluru North | ಸುರದೇನಪುರ | ಸುರಾದೇನಪುರ | yes |
| Thirumalenahalli | Bengaluru South | ತಿರುಮೇನಹಳ್ಳಿ | ತಿರುಮಲೇನಹಳ್ಳಿ | yes |
| Jeerga K | Aurad | ಜಿರ್ಗಾ | ಜೀರಗಾ ಕೆ | yes |
| Sonala | Aurad | ಸೋನಾಳ | ಸೋನಾಳಾ | yes |
| Saigaon | Bhalki | ಸಾಯಗಾಂವ | ಸಾಯಿಗಾಂವ | yes |
| Allapur | Bidar | ಅಲ್ಲಪುರ | ಅಲ್ಲಾಪುರ | yes |
| Hilalpur | Homnabad | ಹಿಲಾಲಪೂರ | ಹಿಲಾಲ್ಪುರ | yes |
| Alipur | Homnabad | ಅಲಿಪೂರ | ಅಲಿಪುರ | yes |
