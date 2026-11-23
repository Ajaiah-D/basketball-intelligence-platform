# Similar players: evaluation

Written by `scripts/evaluate_similarity.py` against the full local warehouse.
The method is in `dashboard/lib/similarity.py`, the tests in
`dashboard/lib/similarity_eval.py`.

## The current model's blocks

- **Scoring** (weight 3): 3PA rate (1), 3PA/36 (1), FT rate (1)
- **Creation** (weight 2): AST% (1), TOV% (1)
- **Rebounding** (weight 1.5): OREB% (1), DREB% (1), height (0.5)
- **Defense** (weight 1.5): STL% (1), BLK% (1), share of shots defended at the rim (1), fouls/36 (0.5), contests/36 (0.5), deflections/36 (0.5)
- **Role** (weight 1): MIN (1), USG% (1), PTS/36 (1), TS% (1)

## Self-match

Each player's season-one profile is compared with every season-two profile;
the closer his own season two ranks, the better the model captures a stable
style. Height and role size are stable by nature, so the rows without them
show how much of the result is style.

| Seasons | Model | Players | Found himself 1st | In top 5 | Median rank |
|---|---|---|---|---|---|
| 2005-06 to 2006-07 | First version (cosine, 12 rates) | 268 of 328 | 48% | 66% | 2 |
| 2005-06 to 2006-07 | Current model | 268 of 328 | 54% | 77% | 1 |
| 2005-06 to 2006-07 | Current, no height | 268 of 328 | 51% | 73% | 1 |
| 2005-06 to 2006-07 | Current, no height or role | 268 of 328 | 47% | 73% | 2 |
| 2014-15 to 2015-16 | First version (cosine, 12 rates) | 291 of 351 | 37% | 66% | 3 |
| 2014-15 to 2015-16 | Current model | 291 of 351 | 53% | 74% | 1 |
| 2014-15 to 2015-16 | Current, no height | 291 of 351 | 49% | 73% | 2 |
| 2014-15 to 2015-16 | Current, no height or role | 291 of 351 | 44% | 69% | 2 |
| 2022-23 to 2023-24 | First version (cosine, 12 rates) | 293 of 360 | 42% | 70% | 2 |
| 2022-23 to 2023-24 | Current model | 293 of 360 | 56% | 80% | 1 |
| 2022-23 to 2023-24 | Current, no height | 293 of 360 | 51% | 78% | 1 |
| 2022-23 to 2023-24 | Current, no height or role | 293 of 360 | 45% | 75% | 2 |
| 2023-24 to 2024-25 | First version (cosine, 12 rates) | 288 of 375 | 43% | 71% | 2 |
| 2023-24 to 2024-25 | Current model | 288 of 375 | 55% | 81% | 1 |
| 2023-24 to 2024-25 | Current, no height | 288 of 375 | 53% | 80% | 1 |
| 2023-24 to 2024-25 | Current, no height or role | 288 of 375 | 48% | 73% | 2 |
| 2024-25 to 2025-26 | First version (cosine, 12 rates) | 289 of 380 | 38% | 65% | 3 |
| 2024-25 to 2025-26 | Current model | 289 of 380 | 50% | 75% | 1 |
| 2024-25 to 2025-26 | Current, no height | 289 of 380 | 47% | 73% | 2 |
| 2024-25 to 2025-26 | Current, no height or role | 289 of 380 | 44% | 72% | 2 |

## Sanity panel

Each player's closest matches, closest first. Read by eye: no number says
these are right.

### 2025-26 (380 players, 500+ minutes)

| Player | First version | Current model |
|---|---|---|
| Jayson Tatum | Jalen Johnson, Michael Porter Jr., Bam Adebayo, Luka Dončić, Pascal Siakam, Brandin Podziemski, Jaylen Brown, Paul George | Michael Porter Jr., Jalen Green, Bam Adebayo, Paul George, Kawhi Leonard, Trey Murphy III, Brandin Podziemski, Brandon Miller |
| Nikola Jokić | Giannis Antetokounmpo, Jalen Johnson, Luka Dončić, LeBron James, Alperen Sengun, Deni Avdija, Karl-Anthony Towns, Julius Randle | Jalen Johnson, Giannis Antetokounmpo, Alperen Sengun, Josh Giddey, LeBron James, Deni Avdija, Paolo Banchero, Cade Cunningham |
| Stephen Curry | Donovan Mitchell, Anthony Edwards, Brandon Miller, Jamal Murray, Keyonte George, Shai Gilgeous-Alexander, Luka Dončić, Norman Powell | Donovan Mitchell, Grayson Allen, Anthony Edwards, Jordan Poole, Brandon Miller, Jalen Green, Tyrese Maxey, Coby White |
| Giannis Antetokounmpo | Nikola Jokić, Joel Embiid, Deni Avdija, Luka Dončić, Alperen Sengun, Julius Randle, Paolo Banchero, Jaylen Brown | Nikola Jokić, Paolo Banchero, Alperen Sengun, Joel Embiid, Deni Avdija, Zion Williamson, Jalen Johnson, Julius Randle |
| Rudy Gobert | Moussa Diabaté, Daniel Gafford, Neemias Queta, Wendell Carter Jr., Mitchell Robinson, Mark Williams, Jarrett Allen, Nic Claxton | Moussa Diabaté, Daniel Gafford, Jalen Duren, Steven Adams, Mitchell Robinson, Jarrett Allen, Mark Williams, Adem Bona |
| Jalen Brunson | Jamal Murray, Devin Booker, CJ McCollum, Tyler Herro, Keyonte George, Desmond Bane, De'Aaron Fox, Donovan Mitchell | Jamal Murray, Tyrese Maxey, De'Aaron Fox, Donovan Mitchell, Devin Booker, CJ McCollum, Andrew Nembhard, Keyonte George |
| Herbert Jones | Cason Wallace, Marcus Smart, Aaron Wiggins, Jahmai Mashack, Alex Caruso, Rayan Rupert, Nique Clifford, Elijah Harkless | Rayan Rupert, Justin Edwards, Aaron Wiggins, Will Richard, Patrick Williams, Cason Wallace, VJ Edgecombe, Ryan Dunn |
| Draymond Green | Bub Carrington, Vince Williams Jr., Lonzo Ball, Walter Clayton Jr., Egor Dëmin, Kyshawn George, Josh Hart, Nolan Traore | Bub Carrington, Vince Williams Jr., Walter Clayton Jr., Nolan Traore, Kyshawn George, Russell Westbrook, Josh Hart, Gui Santos |
| Mikal Bridges | Andrew Wiggins, Devin Vassell, Miles McBride, VJ Edgecombe, Derrick White, Moses Moody, Tristan da Silva, Rui Hachimura | Andrew Wiggins, Tristan da Silva, VJ Edgecombe, Devin Vassell, Kevin Huerter, Ayo Dosunmu, Tobias Harris, Ace Bailey |
| Victor Wembanyama | Evan Mobley, Kristaps Porziņģis, Chet Holmgren, Anthony Davis, Joel Embiid, Alex Sarr, Jaren Jackson Jr., Giannis Antetokounmpo | Chet Holmgren, Kristaps Porziņģis, Evan Mobley, Karl-Anthony Towns, Joel Embiid, Bam Adebayo, Tristan Vukcevic, Anthony Davis |
| Shai Gilgeous-Alexander | Donovan Mitchell, Anthony Edwards, Tyrese Maxey, Keyonte George, Luka Dončić, Devin Booker, Jamal Murray, Stephen Curry | Devin Booker, Keyonte George, Jamal Murray, Jaylen Brown, Jalen Williams, Tyrese Maxey, Franz Wagner, Tre Jones |
| Derrick White | VJ Edgecombe, Andrew Wiggins, Mikal Bridges, Keegan Murray, CJ McCollum, Ace Bailey, Tyrese Maxey, Anthony Black | CJ McCollum, Malik Monk, Kevin Huerter, Immanuel Quickley, Nickeil Alexander-Walker, Brandon Miller, Collin Gillespie, Trey Murphy III |

### 2026-27 (284 players, 178+ minutes)

| Player | First version | Current model |
|---|---|---|
| Jayson Tatum | Cade Cunningham, Deni Avdija, Franz Wagner, Luka Dončić, Shai Gilgeous-Alexander, Donovan Mitchell, Keyonte George, Jalen Brunson | Cade Cunningham, Deni Avdija, Keyonte George, Ty Jerome, Jamal Murray, Donovan Mitchell, Franz Wagner, Tyler Herro |
| Nikola Jokić | Franz Wagner, Alperen Sengun, Jalen Johnson, Cooper Flagg, Cade Cunningham, Luka Dončić, Scottie Barnes, LeBron James | Jalen Johnson, Cooper Flagg, Alperen Sengun, Franz Wagner, LeBron James, Cameron Boozer, Cade Cunningham, Scottie Barnes |
| Stephen Curry | Donovan Mitchell, Ty Jerome, Tyler Herro, Damian Lillard, Tyrese Maxey, Luka Dončić, Pascal Siakam, Deni Avdija | Damian Lillard, Ty Jerome, Luka Dončić, Kyrie Irving, Jayson Tatum, Tyler Herro, Donovan Mitchell, Tyrese Maxey |
| Giannis Antetokounmpo | Alperen Sengun, Karl-Anthony Towns, Victor Wembanyama, Joel Embiid, Yaxel Lendeborg, Anthony Davis, Nikola Jokić, Deni Avdija | Alperen Sengun, Joel Embiid, Karl-Anthony Towns, Jalen Johnson, Nikola Jokić, Derik Queen, Anthony Davis, Cooper Flagg |
| Rudy Gobert | Joan Beringer, Oso Ighodaro, Gui Santos, Neemias Queta, Luke Kornet, Jarrett Allen, Ivica Zubac, Wendell Carter Jr. | Neemias Queta, Joan Beringer, Jaxson Hayes, Jarrett Allen, Oso Ighodaro, Mitchell Robinson, Wendell Carter Jr., Walker Kessler |
| Jalen Brunson | Tyler Herro, Ty Jerome, Devin Booker, Shai Gilgeous-Alexander, Darius Acuff Jr., Kyrie Irving, Tyrese Maxey, Donovan Mitchell | Ty Jerome, Shai Gilgeous-Alexander, Tyrese Maxey, Devin Booker, Immanuel Quickley, Tyler Herro, Jamal Murray, Darius Acuff Jr. |
| Herbert Jones | Mikal Bridges, Jase Richardson, Svi Mykhailiuk, Emanuel Sharp, Sion James, Josh Hart, Keegan Murray, Luguentz Dort | Mikal Bridges, Svi Mykhailiuk, Jase Richardson, Georges Niang, Baylor Scheierman, Peyton Watson, Chaney Johnson, Kobe Sanders |
| Draymond Green | Jalen Suggs, Josh Giddey, Kingston Flemings, Dennis Schröder, Jamal Shead, Myles Turner, Sion James, Jake LaRavia | Kingston Flemings, Josh Giddey, Dennis Schröder, Jalen Suggs, Jamal Shead, Kris Dunn, Ausar Thompson, Dejounte Murray |
| Mikal Bridges | Herbert Jones, Jase Richardson, Josh Hart, Keegan Murray, Svi Mykhailiuk, Emanuel Sharp, Keon Ellis, Zaccharie Risacher | Herbert Jones, Kevin Huerter, Jase Richardson, Caleb Martin, Keegan Murray, Georges Niang, VJ Edgecombe, Kobe Sanders |
| Victor Wembanyama | Giannis Antetokounmpo, Anthony Davis, Brook Lopez, Karl-Anthony Towns, Scottie Barnes, Yaxel Lendeborg, Joel Embiid, Alperen Sengun | Karl-Anthony Towns, Brook Lopez, Anthony Davis, Giannis Antetokounmpo, Jalen Smith, Joel Embiid, Yaxel Lendeborg, Evan Mobley |
| Shai Gilgeous-Alexander | Jalen Brunson, Devin Booker, Ty Jerome, Tyler Herro, Jayson Tatum, Donovan Mitchell, Tyrese Maxey, Pascal Siakam | Devin Booker, Jalen Brunson, Tyrese Maxey, Jamal Murray, Pascal Siakam, Ty Jerome, Tyler Herro, RJ Barrett |
| Derrick White | Fred VanVleet, CJ McCollum, Davion Mitchell, Collin Gillespie, Jamal Shead, Daniss Jenkins, Mikal Bridges, Kevin Huerter | CJ McCollum, Daniss Jenkins, Stephon Castle, Nolan Traore, Kevin Huerter, Brandin Podziemski, Payton Pritchard, Jrue Holiday |
