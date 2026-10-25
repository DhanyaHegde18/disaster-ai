# River flood levels (GloFAS v4 via Open-Meteo)

Built 2026-10-25 from June-November discharge, 2005-2022 (18 yearly peaks per point). MEDIUM = level reached about every 2nd year, HIGH = about every 5th year.

**Sanity check:** the three biggest years at each point should include a year Karnataka remembers for river floods (2009, 2018, 2019). That holds at **23 of 26 points**. A small stream beside a big river floods in the same years, so this check alone is weak.

**Size check:** a big river's record flood is hundreds to thousands of m³/s. **1 of 26 points** stay below 300 m³/s (⚠ small) even after moving each point onto the biggest river within about 11 km: they are left out of live warnings. Check them on the map or remove them from ml/data/river_points.csv (dam-controlled rivers like the Kali and Sharavathi can look small in GloFAS).

| Point | MEDIUM m³/s | HIGH m³/s | Record m³/s | Biggest years | Moved | Villages warned |
|---|---|---|---|---|---|---|
| Krishna at Kudachi | 5,041 | 6,552 | 11,428 | 2019, 2020, 2008 | – | 17 |
| Krishna at Almatti | 6,004 | 8,056 | 13,212 | 2019, 2020, 2008 | – | 43 |
| Krishna at Narayanpur | 6,769 | 9,398 | 14,060 | 2019, 2020, 2013 | 5.3 km | 42 |
| Krishna at Deosugur | 11,417 | 14,770 | 23,877 | 2019, 2009, 2020 | – | 21 |
| Bhima at Afzalpur | 4,356 | 6,197 | 10,092 | 2019, 2020, 2006 | 7.7 km | 27 |
| Bhima at Jewargi | 4,400 | 6,771 | 10,303 | 2019, 2020, 2006 | – | 24 |
| Bhima at Yadgir | 4,491 | 7,418 | 10,616 | 2019, 2020, 2009 | 7.7 km | 24 |
| Ghataprabha at Gokak | 1,210 | 1,646 | 1,976 | 2019, 2020, 2008 | – | 23 |
| Ghataprabha at Bagalkot | 1,413 | 1,722 | 2,112 | 2019, 2020, 2022 | – | 29 |
| Malaprabha at Ramdurg | 400 | 716 | 1,041 | 2020, 2013, 2019 | – | 32 |
| Tungabhadra at Harihar | 2,118 | 2,890 | 4,538 | 2021, 2009, 2020 | 5.4 km | 47 |
| Tungabhadra at Hampi | 2,878 | 4,076 | 9,204 | 2021, 2009, 2020 | 5.4 km | 51 |
| Tungabhadra at Siruguppa | 2,993 | 4,163 | 10,256 | 2009, 2021, 2020 | 10.7 km | 23 |
| Tunga at Shivamogga | 1,679 | 2,081 | 2,534 | 2021, 2011, 2020 ⚠ | 12.4 km | 37 |
| Bhadra at Bhadravati | 740 | 882 | 1,204 | 2011, 2021, 2020 ⚠ | – | 61 |
| Kali at Dandeli | 652 | 779 | 922 | 2019, 2008, 2013 | 5.6 km | 19 |
| Sharavathi at Honnavar | 611 | 842 | 974 | 2007, 2011, 2022 ⚠ | 5.4 km | 20 |
| Aghanashini at Kumta | 735 | 824 | 917 | 2020, 2021, 2019 | – | 40 |
| Netravati at Bantwal | 1,146 | 1,426 | 1,492 | 2009, 2019, 2020 | – | 27 |
| Netravati at Uppinangady | 1,054 | 1,307 | 1,383 | 2009, 2019, 2020 | 5.4 km | 23 |
| Kumaradhara at Subrahmanya | 173 | 208 | 232 ⚠ small | 2018, 2009, 2020 | 12.2 km | 13 |
| Cauvery at Kushalnagar | 430 | 603 | 678 | 2018, 2007, 2022 | 5.4 km | 24 |
| Cauvery at Srirangapatna | 807 | 1,350 | 1,814 | 2011, 2020, 2009 | – | 56 |
| Cauvery at Shivanasamudra | 1,488 | 2,212 | 2,804 | 2011, 2020, 2018 | 5.4 km | 33 |
| Kabini at Nanjangud | 925 | 1,040 | 1,376 | 2018, 2021, 2011 | – | 35 |
| Hemavathi at Holenarasipur | 481 | 674 | 823 | 2011, 2009, 2020 | 5.4 km | 88 |

Limits: GloFAS is a model, not a gauge. It represents big dams in a simplified way, while real releases from Almatti, Narayanpur, Tungabhadra or Kabini are decided by people, so warnings are a guide to check with the river and dam authorities (CWC, KNNL), not a measurement.
