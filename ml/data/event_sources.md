# Event sources (draft, check each before trusting it)

Confidence:
- **High**: the article names the place and the date (or an unambiguous weekday).
- **Medium**: the date is inferred from a weekday, or the place is 10–20 km from our village point.

Always label the date the event **happened**, not the date the article was published.

## Rows already in events.csv

| village_id | date | type | confidence | evidence | source |
|---|---|---|---|---|---|
| V008 Agumbe | 2018-06-29 | landslide | High | Landslide at the 7th curve of Agumbe Ghat on 29 June (mentioned in a later article). | [The News Minute, 13 Jul 2018](https://www.thenewsminute.com/karnataka/another-landslide-agumbe-ghat-due-heavy-rains-traffic-disrupted-again-84710) |
| V008 Agumbe | 2018-07-13 | landslide | Medium | Landslide near Agumbe Sunset Point "on Friday"; article published Friday 13 Jul. | same as above |
| V004 Madikeri | 2018-08-12 | landslide | Medium | Landslide near a house in Tyagaraja Colony, Madikeri, after "Sunday night" rain. Page shows two dates (published 13 Aug, updated 12 Oct), so check. | [Deccan Herald](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Fheavy-rain-leads-landslide-687354.html) |
| V007 Sakleshpur | 2018-08-14 | landslide | High | Multiple landslides in Sakleshpur taluk "on Tuesday" disrupted road and rail; article published Tue 14 Aug. | [Deccan Herald, 14 Aug 2018](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Flandslides-many-places-hit-687584.html) |
| V003 Subrahmanya | 2018-08-16 | flood | Medium | Flooding at Subrahmanya "receded on Friday morning" (17 Aug); Kumaradhara bathing ghat cut off, Hosamata bridge submerged. Exact start date not given. | [Deccan Herald, 17 Aug 2018](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Fsubrahmanya-uppinangady-floods-687959.html) |
| V004 Madikeri | 2018-08-16 | landslide | High | Makkandur (near Madikeri) washed away by landslide on Thursday 16 Aug; flooding began early 16 Aug. Makkandur is roughly 10 km from Madikeri, so check the distance. | [The News Minute, 17 Aug 2018](https://www.thenewsminute.com/article/inside-relief-camps-madikeri-survivors-recount-their-escape-kodagu-floods-86761), [The Quint, 17 Aug 2018](https://thequint.com/news/india/flood-rain-two-storey-building-sliding-down-hill-kodagu-shows-how-bad-rains) |
| V002 Belthangady | 2019-08-09 | flood | High date / Medium place | Flash flood from a 1–5 pm downpour on 9 Aug 2019 hit Didupe and nearby villages. Didupe is in Belthangady taluk but ~15–20 km from Belthangady town. | [Deccan Herald, 15 Aug 2019](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Ffloods-gone-people-now-grapple-with-vast-devastation-754400.html) |

## Real events too far from our 8 points: add them as new villages

These happened, but not close enough to any village in villages.csv to label honestly.
Add a row to villages.csv (look up the coordinates on a map), re-run fetch_rainfall.py, then add the event.

| Place | Date | Type | Evidence | Source |
|---|---|---|---|---|
| Charmadi / Didupe (Belthangady taluk) | 2019-08-09 to 2019-08-10 | landslide | Charmadi Ghat closed on 10 Aug after landslides; villages Charmadi and Didupe affected. | [The News Minute, 15 Aug 2019](https://www.thenewsminute.com/amp/story/karnataka/charmadi-ghat-road-connecting-coastal-karnataka-rest-state-closed-after-landslides-107283) |
| Talacauvery, Brahmagiri hills (Kodagu) | 2020-08-06 | landslide | Landslide in the early hours of Thursday 6 Aug; four missing. | [The News Minute, 6 Aug 2020](https://www.thenewsminute.com/article/heavy-rain-kodagu-causes-landslide-four-persons-missing-130159) |
| Shiradi Ghat | 2018-08-13 and 2018-08-20 | landslide | Boulders at three places on Monday night 13 Aug; 26 landslips on Monday 20 Aug. | [Deccan Herald, 14 Aug 2018](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Flandslides-many-places-hit-687584.html), [Deccan Herald, 20 Aug 2018](https://www.deccanherald.com/state/landslides-45-places-shiradi-688556.html) |
| Karthoji, Madikeri–Mangaluru highway | 2025-05-26 | landslide | Hill caved in, traffic stopped. Check how far Karthoji is from Madikeri; if within ~5 km, label it V004. | [Sphere India SitRep, May 2025](https://www.sphereindia.org.in/sites/default/files/2025-06/SitRep%201_Karnatkaa%20Rainfall.pdf) |

## Recent events (August 2026): extend the rainfall dates first

Your rainfall data ends on 2025-12-31. These need `--end 2026-09-30` before they can be used.
Delete ml/data/raw/rainfall and re-download, because the script skips files that already exist.

| Place | Date | Type | Evidence | Source |
|---|---|---|---|---|
| Ujire / Mundaje (V001) | 2026-08-01 to 2026-08-02 | flood | Low-lying plantations, farmland and houses submerged in Mundaje and Ujire after overnight rain; Mundaje got 348.5 mm in 24 h. | [Siasat/PTI, 2 Aug 2026](https://www.siasat.com/heavy-rains-trigger-landslides-flooding-in-dakshina-kannada-3517692/), [The Week, 2 Aug 2026](https://www.theweek.in/news/india/2026/08/02/karnataka-rivers-overflow-after-heavy-rains-lash-state-landslide-kills-family-of-three.html) |
| Kalasa (V005) | ~2026-08-01 to 02 | flood | Bhadra overflowed; Kalasa–Kudremukh road cut. Exact date not stated. | The Week, as above |
| Sringeri (V006) | ~2026-08 (unclear) | flood | Tunga flooded, traffic suspended. The article's weekday doesn't match, so find the exact date. | The Week, as above |
| Sakleshpur taluk (V007) | ~2026-08-01 to 02 | landslide | Landslide near Yadakumari–Shiravagilu cancelled trains. | The Week, as above |

## Useful "no event" evidence

- **25–26 May 2025, Ujire/Belthangady:** very heavy rain in your data, but a state situation report listed no flood or landslide incidents for Belthangady or Ujire. Leave these days unlabelled (label 0). They teach the model that heavy rain alone isn't always a disaster. ([Sphere India SitRep](https://www.sphereindia.org.in/sites/default/files/2025-06/SitRep%201_Karnatkaa%20Rainfall.pdf))

## Not used as events

- **Kukke Subrahmanya bathing ghat submerged** (e.g. ~6–7 Aug 2020): this happens almost every heavy monsoon spell and causes little damage. Labelling every one would teach the model "monsoon = disaster". Leave these out unless real damage is reported. ([Deccan Herald, 7 Aug 2020](https://deccanherald.com/india/karnataka/snanaghatta-of-kukke-subrahmanya-remains-inundated-870595.html))
- **Agumbe minor landslides, late May 2025**: real but no exact date given.