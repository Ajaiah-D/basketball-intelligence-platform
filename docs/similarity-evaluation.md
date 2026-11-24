# Similar players: evaluation

Written by `scripts/evaluate_similarity.py` against the full local warehouse.
The method is in `dashboard/lib/similarity.py`, the tests in
`dashboard/lib/similarity_eval.py`.

## The current model's blocks

- **Shot diet** (weight 1.5): share of shots at the rim (1), in the paint (1), mid-range (1), corner 3 (1), above-the-break 3 (1), 3PA/36 (1), FT rate (1)
- **Play type** (weight 1.5): isolation (1), transition (1), pick-and-roll handler (1), roll man (1), post-up (1), spot-up (1), handoff (1), cut (1), off screen (1), putback (1)
- **Creation** (weight 2): AST% (1), TOV% (1), screen assists/36 (1)
- **Rebounding** (weight 1.5): OREB% (1), DREB% (1), height (0.5)
- **Defense** (weight 1.5): STL% (1), BLK% (1), share of shots defended at the rim (1), fouls/36 (0.5), contests/36 (0.5), deflections/36 (0.5)
- **Role** (weight 1): MIN (1), USG% (1), PTS/36 (1), TS% (1)

Play-type shares are shrunk toward the pool's average by 100
possessions of it (ten per play type, the NBA's own floor for listing one).
Shot zones exist from 1996-97 and play types from 2015-16; a season without
them goes without those features. 2023-24's play types are missing for too
many players (the NBA's answer lacks rows), so that season goes without them.

## Self-match

Each player's season-one profile is compared with every season-two profile;
the closer his own season two ranks, the better the model captures a stable
style. Height and role size are stable by nature, so the rows without them
show how much of the result is style.

| Seasons | Model | Players | Found himself 1st | In top 5 | Median rank |
|---|---|---|---|---|---|
| 2005-06 to 2006-07 | First version (cosine, 12 rates) | 268 of 328 | 48% | 66% | 2 |
| 2005-06 to 2006-07 | Before shot data | 268 of 328 | 54% | 77% | 1 |
| 2005-06 to 2006-07 | Current model | 268 of 328 | 61% | 80% | 1 |
| 2005-06 to 2006-07 | Current, play types not shrunk | 268 of 328 | 61% | 80% | 1 |
| 2005-06 to 2006-07 | Current, no height | 268 of 328 | 59% | 78% | 1 |
| 2005-06 to 2006-07 | Current, no height or role | 268 of 328 | 57% | 74% | 1 |
| 2014-15 to 2015-16 | First version (cosine, 12 rates) | 291 of 351 | 37% | 66% | 3 |
| 2014-15 to 2015-16 | Before shot data | 291 of 351 | 53% | 74% | 1 |
| 2014-15 to 2015-16 | Current model | 291 of 351 | 58% | 78% | 1 |
| 2014-15 to 2015-16 | Current, play types not shrunk | 291 of 351 | 58% | 78% | 1 |
| 2014-15 to 2015-16 | Current, no height | 291 of 351 | 56% | 77% | 1 |
| 2014-15 to 2015-16 | Current, no height or role | 291 of 351 | 50% | 75% | 1 |
| 2017-18 to 2018-19 | First version (cosine, 12 rates) | 281 of 361 | 37% | 64% | 3 |
| 2017-18 to 2018-19 | Before shot data | 281 of 361 | 51% | 77% | 1 |
| 2017-18 to 2018-19 | Current model | 281 of 361 | 67% | 90% | 1 |
| 2017-18 to 2018-19 | Current, play types not shrunk | 281 of 361 | 68% | 89% | 1 |
| 2017-18 to 2018-19 | Current, no height | 281 of 361 | 67% | 89% | 1 |
| 2017-18 to 2018-19 | Current, no height or role | 281 of 361 | 62% | 85% | 1 |
| 2022-23 to 2023-24 | First version (cosine, 12 rates) | 293 of 360 | 42% | 70% | 2 |
| 2022-23 to 2023-24 | Before shot data | 293 of 360 | 57% | 81% | 1 |
| 2022-23 to 2023-24 | Current model | 293 of 360 | 66% | 85% | 1 |
| 2022-23 to 2023-24 | Current, play types not shrunk | 293 of 360 | 66% | 85% | 1 |
| 2022-23 to 2023-24 | Current, no height | 293 of 360 | 61% | 83% | 1 |
| 2022-23 to 2023-24 | Current, no height or role | 293 of 360 | 57% | 82% | 1 |
| 2023-24 to 2024-25 | First version (cosine, 12 rates) | 288 of 375 | 43% | 71% | 2 |
| 2023-24 to 2024-25 | Before shot data | 288 of 375 | 56% | 82% | 1 |
| 2023-24 to 2024-25 | Current model | 288 of 375 | 65% | 86% | 1 |
| 2023-24 to 2024-25 | Current, play types not shrunk | 288 of 375 | 65% | 86% | 1 |
| 2023-24 to 2024-25 | Current, no height | 288 of 375 | 62% | 85% | 1 |
| 2023-24 to 2024-25 | Current, no height or role | 288 of 375 | 59% | 81% | 1 |
| 2024-25 to 2025-26 | First version (cosine, 12 rates) | 289 of 380 | 38% | 65% | 3 |
| 2024-25 to 2025-26 | Before shot data | 289 of 380 | 53% | 78% | 1 |
| 2024-25 to 2025-26 | Current model | 289 of 380 | 63% | 83% | 1 |
| 2024-25 to 2025-26 | Current, play types not shrunk | 289 of 380 | 64% | 83% | 1 |
| 2024-25 to 2025-26 | Current, no height | 289 of 380 | 61% | 82% | 1 |
| 2024-25 to 2025-26 | Current, no height or role | 289 of 380 | 60% | 82% | 1 |

## Known pairs

Rank of the other player on his page (1 = closest). A pair that should match
holds in the top 5; one that shouldn't holds outside the top
10. The pairs are judgement calls and count beside self-match.

### 2025-26

| On his page | Other | Want | Why | First version (cosine, 12 rates) | Before shot data | Current model |
|---|---|---|---|---|---|---|
| Nikola Jokić | Alperen Sengun | top 5 | post-up hub bigs who pass and screen | 5 (yes) | 3 (yes) | 1 (yes) |
| Domantas Sabonis | Nikola Jokić | top 5 | hub bigs: handoffs, screens, elbow passing | 7 (no) | 21 (no) | 18 (no) |
| Rudy Gobert | Jarrett Allen | top 5 | rim-running centers who don't shoot | 7 (no) | 6 (no) | 24 (no) |
| Brook Lopez | Myles Turner | top 5 | stretch centers who protect the rim | 3 (yes) | 2 (yes) | 1 (yes) |
| Victor Wembanyama | Chet Holmgren | top 5 | long shot-blockers who shoot threes | 3 (yes) | 1 (yes) | 1 (yes) |
| Bam Adebayo | Evan Mobley | top 5 | switchable bigs who pass on the roll | 18 (no) | 18 (no) | 18 (no) |
| Mitchell Robinson | Steven Adams | top 5 | offensive rebounders and screeners | 21 (no) | 13 (no) | 12 (no) |
| Giannis Antetokounmpo | Zion Williamson | top 5 | downhill rim attackers, few threes | 9 (no) | 4 (yes) | 13 (no) |
| Luka Dončić | James Harden | top 5 | step-back, pick-and-roll lead creators | 4 (yes) | 1 (yes) | 2 (yes) |
| Derrick White | Jrue Holiday | top 5 | 3-and-D combo guards | 72 (no) | 68 (no) | 80 (no) |
| Herbert Jones | Dyson Daniels | top 5 | disruptive wing defenders | 46 (no) | 210 (no) | 158 (no) |
| Nikola Jokić | Jalen Johnson | not top 10 | same output, not the post, screens or matchups | 2 (no) | 2 (no) | 3 (no) |
| Jayson Tatum | Cade Cunningham | not top 10 | high-volume shooting wing vs lead guard | 19 (yes) | 57 (yes) | 34 (yes) |
| Rudy Gobert | Brook Lopez | not top 10 | both protect the rim, score in opposite places | 170 (yes) | 177 (yes) | 99 (yes) |

### 2026-27

| On his page | Other | Want | Why | First version (cosine, 12 rates) | Before shot data | Current model |
|---|---|---|---|---|---|---|
| Nikola Jokić | Alperen Sengun | top 5 | post-up hub bigs who pass and screen | 1 (yes) | 1 (yes) | 1 (yes) |
| Domantas Sabonis | Nikola Jokić | top 5 | hub bigs: handoffs, screens, elbow passing | 23 (no) | 17 (no) | 22 (no) |
| Rudy Gobert | Jarrett Allen | top 5 | rim-running centers who don't shoot | 5 (yes) | 4 (yes) | 3 (yes) |
| Brook Lopez | Myles Turner | top 5 | stretch centers who protect the rim | 182 (no) | 74 (no) | 50 (no) |
| Victor Wembanyama | Chet Holmgren | top 5 | long shot-blockers who shoot threes | under the floor | under the floor | under the floor |
| Bam Adebayo | Evan Mobley | top 5 | switchable bigs who pass on the roll | 38 (no) | 9 (no) | 5 (yes) |
| Mitchell Robinson | Steven Adams | top 5 | offensive rebounders and screeners | under the floor | under the floor | under the floor |
| Giannis Antetokounmpo | Zion Williamson | top 5 | downhill rim attackers, few threes | 33 (no) | 32 (no) | 27 (no) |
| Luka Dončić | James Harden | top 5 | step-back, pick-and-roll lead creators | 23 (no) | 11 (no) | 14 (no) |
| Derrick White | Jrue Holiday | top 5 | 3-and-D combo guards | 81 (no) | 14 (no) | 5 (yes) |
| Herbert Jones | Dyson Daniels | top 5 | disruptive wing defenders | 62 (no) | 187 (no) | 190 (no) |
| Nikola Jokić | Jalen Johnson | not top 10 | same output, not the post, screens or matchups | 3 (no) | 3 (no) | 11 (yes) |
| Jayson Tatum | Cade Cunningham | not top 10 | high-volume shooting wing vs lead guard | 2 (no) | 3 (no) | 1 (no) |
| Rudy Gobert | Brook Lopez | not top 10 | both protect the rim, score in opposite places | 138 (yes) | 61 (yes) | 51 (yes) |

- **First version (cosine, 12 rates)**: 9 of 26 pairs hold
- **Before shot data**: 10 of 26 pairs hold
- **Current model**: 12 of 26 pairs hold

## Weightings tried

Self-match (found himself first / in the top 5) and known pairs for each
weighting tried for the shot diet and play types. Pick on both: self-match
rewards stable stats, the pairs are judgement calls.

| Weighting | 2005-06 to 2006-07 | 2014-15 to 2015-16 | 2017-18 to 2018-19 | 2022-23 to 2023-24 | 2023-24 to 2024-25 | 2024-25 to 2025-26 | Known pairs held |
|---|---|---|---|---|---|---|---|
| Before shot data | 54% / 77% | 53% / 74% | 51% / 77% | 57% / 81% | 56% / 82% | 53% / 78% | 10 of 26 |
| One Scoring block, weight 3, not shrunk | 63% / 81% | 60% / 80% | 68% / 89% | 67% / 86% | 67% / 88% | 63% / 82% | 9 of 26 |
| Shot diet 1.5 + Play type 1.5, not shrunk | 61% / 80% | 58% / 78% | 68% / 89% | 66% / 85% | 65% / 86% | 64% / 83% | 10 of 26 |
| Shot diet 1.5 + Play type 1.5, prior 50 | 61% / 80% | 58% / 78% | 68% / 89% | 66% / 85% | 65% / 86% | 63% / 83% | 10 of 26 |
| Shot diet 1.5 + Play type 1.5, prior 100 (current) | 61% / 80% | 58% / 78% | 67% / 90% | 66% / 85% | 65% / 86% | 63% / 83% | 12 of 26 |
| Shot diet 1.5 + Play type 1.5, prior 200 | 61% / 80% | 58% / 78% | 67% / 90% | 66% / 85% | 65% / 86% | 63% / 83% | 12 of 26 |
| Same, 3PA rate kept in Shot diet, prior 100 | 61% / 79% | 58% / 77% | 67% / 90% | 65% / 84% | 65% / 86% | 63% / 82% | 12 of 26 |
| Shot diet 2 + Play type 2, not shrunk | 63% / 80% | 58% / 79% | 70% / 90% | 67% / 86% | 66% / 86% | 64% / 83% | 9 of 26 |
| Shot diet 2 + Play type 2, prior 100 | 63% / 80% | 58% / 79% | 69% / 90% | 67% / 86% | 66% / 86% | 64% / 84% | 11 of 26 |

## Sanity panel

Each player's closest matches, closest first. Read by eye: no number says
these are right.

### 2025-26 (380 players, 500+ minutes)

| Player | Before shot data | Current model |
|---|---|---|
| Jayson Tatum | Michael Porter Jr., Bam Adebayo, Paul George, Jalen Green, Kawhi Leonard, Trey Murphy III, Luka Dončić, Brandin Podziemski | Jalen Johnson, Luka Dončić, Paolo Banchero, Kawhi Leonard, Jalen Green, Jaylen Brown, Pascal Siakam, Brandin Podziemski |
| Nikola Jokić | Giannis Antetokounmpo, Jalen Johnson, Alperen Sengun, Karl-Anthony Towns, Joel Embiid, Domantas Sabonis, Paolo Banchero, Jusuf Nurkić | Alperen Sengun, Giannis Antetokounmpo, Jalen Johnson, Domantas Sabonis, Karl-Anthony Towns, Jusuf Nurkić, Scottie Barnes, Joel Embiid |
| Stephen Curry | Donovan Mitchell, Grayson Allen, Anthony Edwards, Brandon Miller, Jordan Poole, Jalen Green, Nickeil Alexander-Walker, Coby White | Donovan Mitchell, Keyonte George, Jamal Murray, Tyrese Maxey, Anthony Edwards, CJ McCollum, Brandon Miller, Grayson Allen |
| Giannis Antetokounmpo | Nikola Jokić, Paolo Banchero, Alperen Sengun, Zion Williamson, Joel Embiid, Jalen Duren, Deni Avdija, Karl-Anthony Towns | Nikola Jokić, Paolo Banchero, Karl-Anthony Towns, Alperen Sengun, LeBron James, Jalen Johnson, Julius Randle, Scottie Barnes |
| Rudy Gobert | Moussa Diabaté, Daniel Gafford, Steven Adams, Jalen Duren, Mitchell Robinson, Jarrett Allen, Mark Williams, Neemias Queta | Moussa Diabaté, Daniel Gafford, Neemias Queta, Mark Williams, Ryan Kalkbrenner, Mitchell Robinson, Steven Adams, Goga Bitadze |
| Jalen Brunson | Jamal Murray, Tyrese Maxey, CJ McCollum, De'Aaron Fox, Andrew Nembhard, Devin Booker, Donovan Mitchell, Keyonte George | Jamal Murray, Devin Booker, Keyonte George, CJ McCollum, Donovan Mitchell, Andrew Nembhard, Payton Pritchard, De'Aaron Fox |
| Herbert Jones | Rayan Rupert, Justin Edwards, Aaron Wiggins, Will Richard, VJ Edgecombe, Patrick Williams, Cason Wallace, Kevin Huerter | Elijah Harkless, Rayan Rupert, Jake LaRavia, Aaron Wiggins, Justin Edwards, Marcus Smart, Jamir Watkins, Bilal Coulibaly |
| Draymond Green | Bub Carrington, Kyshawn George, Vince Williams Jr., Josh Hart, Jaylin Williams, Walter Clayton Jr., Gui Santos, Nolan Traore | Jaylin Williams, Josh Hart, Gui Santos, Vince Williams Jr., Lonzo Ball, Russell Westbrook, Kyshawn George, Jahmai Mashack |
| Mikal Bridges | Andrew Wiggins, Tristan da Silva, VJ Edgecombe, Kevin Huerter, Devin Vassell, Ayo Dosunmu, Ace Bailey, Zaccharie Risacher | Tristan da Silva, Jaylen Wells, Andrew Wiggins, Devin Vassell, Kevin Huerter, Cameron Johnson, VJ Edgecombe, Miles McBride |
| Victor Wembanyama | Chet Holmgren, Kristaps Porziņģis, Karl-Anthony Towns, Evan Mobley, Bam Adebayo, Joel Embiid, Jaren Jackson Jr., Kyle Filipowski | Chet Holmgren, Evan Mobley, Kristaps Porziņģis, Karl-Anthony Towns, Anthony Davis, Bam Adebayo, Paolo Banchero, Joel Embiid |
| Shai Gilgeous-Alexander | Devin Booker, Keyonte George, Jaylen Brown, Franz Wagner, Austin Reaves, Cade Cunningham, LeBron James, Jalen Williams | Devin Booker, Tyrese Maxey, Donovan Mitchell, Jalen Brunson, Anthony Edwards, Kawhi Leonard, Jamal Murray, Jaylen Brown |
| Derrick White | CJ McCollum, Kevin Huerter, Malik Monk, Nickeil Alexander-Walker, Immanuel Quickley, Brandon Miller, Collin Gillespie, Donte DiVincenzo | CJ McCollum, Collin Gillespie, Brandon Miller, Malik Monk, Grayson Allen, VJ Edgecombe, Reed Sheppard, Brandin Podziemski |

### 2026-27 (281 players, 186+ minutes)

| Player | Before shot data | Current model |
|---|---|---|
| Jayson Tatum | Keyonte George, Deni Avdija, Cade Cunningham, Ty Jerome, Jamal Murray, Donovan Mitchell, Tyler Herro, Franz Wagner | Cade Cunningham, Luka Dončić, Shai Gilgeous-Alexander, Keyonte George, LeBron James, James Harden, Cooper Flagg, Donovan Mitchell |
| Nikola Jokić | Alperen Sengun, Karl-Anthony Towns, Jalen Johnson, Cameron Boozer, Joel Embiid, Giannis Antetokounmpo, Evan Mobley, Franz Wagner | Alperen Sengun, Joel Embiid, Cameron Boozer, Karl-Anthony Towns, Giannis Antetokounmpo, Anthony Davis, Brook Lopez, Bam Adebayo |
| Stephen Curry | Damian Lillard, Luka Dončić, Ty Jerome, Jayson Tatum, Kyrie Irving, Donovan Mitchell, Tyler Herro, Tyrese Maxey | Damian Lillard, Kyrie Irving, Donovan Mitchell, Tyler Herro, Tyrese Maxey, Jalen Brunson, Jamal Murray, Norman Powell |
| Giannis Antetokounmpo | Joel Embiid, Alperen Sengun, Derik Queen, Karl-Anthony Towns, Anthony Davis, Jalen Johnson, Nikola Jokić, Bam Adebayo | Alperen Sengun, Victor Wembanyama, Karl-Anthony Towns, Cameron Boozer, Jalen Johnson, Joel Embiid, Anthony Davis, Derik Queen |
| Rudy Gobert | Neemias Queta, Joan Beringer, Jaxson Hayes, Jarrett Allen, Oso Ighodaro, Mitchell Robinson, Luke Kornet, Walker Kessler | Neemias Queta, Joan Beringer, Jarrett Allen, Walker Kessler, Khaman Maluach, Mitchell Robinson, Jakob Poeltl, Ivica Zubac |
| Jalen Brunson | Ty Jerome, Devin Booker, Tyrese Maxey, Shai Gilgeous-Alexander, Tyler Herro, Immanuel Quickley, Donovan Mitchell, Darius Acuff Jr. | Devin Booker, Shai Gilgeous-Alexander, Kyrie Irving, Tyrese Maxey, Darius Acuff Jr., Tyler Herro, Jamal Murray, Donovan Mitchell |
| Herbert Jones | Mikal Bridges, Jase Richardson, Josh Green, Jordan Walsh, Jalen Suggs, Keegan Murray, Georges Niang, Baylor Scheierman | Mikal Bridges, Chaney Johnson, Georges Niang, Jaylon Tyson, Baylor Scheierman, Peyton Watson, Sion James, Toumani Camara |
| Draymond Green | Kingston Flemings, Josh Giddey, Dennis Schröder, Jalen Suggs, Jake LaRavia, Kris Dunn, Josh Hart, Chaney Johnson | Jalen Suggs, Kingston Flemings, Josh Giddey, Dennis Schröder, Oso Ighodaro, Myles Turner, Chaney Johnson, Jamal Shead |
| Mikal Bridges | Herbert Jones, Kevin Huerter, Patrick Williams, Keegan Murray, Jase Richardson, Kobe Sanders, VJ Edgecombe, Georges Niang | Cameron Johnson, Herbert Jones, Svi Mykhailiuk, Kobe Sanders, Patrick Williams, Baylor Scheierman, Keegan Murray, Georges Niang |
| Victor Wembanyama | Karl-Anthony Towns, Brook Lopez, Anthony Davis, Giannis Antetokounmpo, Cameron Boozer, Alex Sarr, Joel Embiid, Jalen Smith | Giannis Antetokounmpo, Anthony Davis, Karl-Anthony Towns, Joel Embiid, Brook Lopez, Derik Queen, Jalen Smith, Cameron Boozer |
| Shai Gilgeous-Alexander | Devin Booker, Jalen Brunson, Jamal Murray, Tyrese Maxey, Ty Jerome, Pascal Siakam, Tyler Herro, Donovan Mitchell | Jalen Brunson, Devin Booker, Jayson Tatum, Ty Jerome, Jamal Murray, Cade Cunningham, Tyrese Maxey, Kyrie Irving |
| Derrick White | CJ McCollum, Payton Pritchard, Daniss Jenkins, Stephon Castle, Kevin Huerter, Brandin Podziemski, Darryn Peterson, Nolan Traore | Nolan Traore, Daniss Jenkins, CJ McCollum, Payton Pritchard, Jrue Holiday, Darryn Peterson, Brandin Podziemski, Immanuel Quickley |
