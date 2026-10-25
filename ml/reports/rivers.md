# River flood levels (GloFAS v4 via Open-Meteo)

Built 2026-10-25 from June-November discharge, 2005-2022 (18 yearly peaks per point). MEDIUM = level reached about every 2nd year, HIGH = about every 5th year.

**Sanity check:** the three biggest years at each point should include a year Karnataka remembers for river floods (2009, 2018, 2019). That holds at **23 of 26 points**. Points where it doesn't may sit on the wrong river cell: move them a little in ml/data/river_points.csv.

| Point | MEDIUM m³/s | HIGH m³/s | Record m³/s | Biggest years | Villages warned |
|---|---|---|---|---|---|
| Krishna at Kudachi | 5,041 | 6,552 | 11,428 | 2019, 2020, 2008 | 17 |
| Krishna at Almatti | 6,004 | 8,056 | 13,212 | 2019, 2020, 2008 | 43 |
| Krishna at Narayanpur | 3 | 8 | 63 | 2009, 2016, 2021 | 38 |
| Krishna at Deosugur | 11,417 | 14,770 | 23,877 | 2019, 2009, 2020 | 21 |
| Bhima at Afzalpur | 8 | 19 | 42 | 2007, 2009, 2010 | 24 |
| Bhima at Jewargi | 4,400 | 6,771 | 10,303 | 2019, 2020, 2006 | 24 |
| Bhima at Yadgir | 7 | 18 | 38 | 2020, 2007, 2009 | 28 |
| Ghataprabha at Gokak | 1,210 | 1,646 | 1,976 | 2019, 2020, 2008 | 23 |
| Ghataprabha at Bagalkot | 1,413 | 1,722 | 2,112 | 2019, 2020, 2022 | 29 |
| Malaprabha at Ramdurg | 400 | 716 | 1,041 | 2020, 2013, 2019 | 32 |
| Tungabhadra at Harihar | 20 | 28 | 137 | 2009, 2021, 2005 | 47 |
| Tungabhadra at Hampi | 1 | 5 | 58 | 2009, 2007, 2021 | 46 |
| Tungabhadra at Siruguppa | 1 | 3 | 11 | 2009, 2007, 2016 | 27 |
| Tunga at Shivamogga | 981 | 1,201 | 1,348 | 2021, 2020, 2011 ⚠ | 55 |
| Bhadra at Bhadravati | 740 | 882 | 1,204 | 2011, 2021, 2020 ⚠ | 61 |
| Kali at Dandeli | 26 | 36 | 45 | 2019, 2008, 2013 | 17 |
| Sharavathi at Honnavar | 76 | 81 | 91 | 2019, 2021, 2011 | 40 |
| Aghanashini at Kumta | 735 | 824 | 917 | 2020, 2021, 2019 | 40 |
| Netravati at Bantwal | 1,146 | 1,426 | 1,492 | 2009, 2019, 2020 | 27 |
| Netravati at Uppinangady | 12 | 14 | 16 | 2019, 2011, 2020 | 19 |
| Kumaradhara at Subrahmanya | 36 | 45 | 49 | 2009, 2020, 2018 | 6 |
| Cauvery at Kushalnagar | 3 | 5 | 7 | 2009, 2022, 2018 | 38 |
| Cauvery at Srirangapatna | 807 | 1,350 | 1,814 | 2011, 2020, 2009 | 56 |
| Cauvery at Shivanasamudra | 0 | 2 | 8 | 2022, 2010, 2021 ⚠ | 18 |
| Kabini at Nanjangud | 925 | 1,040 | 1,376 | 2018, 2021, 2011 | 35 |
| Hemavathi at Holenarasipur | 4 | 9 | 15 | 2009, 2011, 2020 | 78 |

Limits: GloFAS is a model, not a gauge. It represents big dams in a simplified way, while real releases from Almatti, Narayanpur, Tungabhadra or Kabini are decided by people, so warnings are a guide to check with the river and dam authorities (CWC, KNNL), not a measurement.
