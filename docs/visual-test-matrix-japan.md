# Japan Visual Discovery Test Matrix

This matrix defines the first golden set for the Gemini visual-first Lens goal. It focuses on Japan cases the product should handle well: Fukuoka/Kyushu and Kansai landmarks, shrines, streets, scenic places, and culturally specific objects.

## Evaluation Rules

- Input must work with one image and no user text.
- A correct answer may use English, Japanese, or Chinese canonical names.
- If the image is not distinctive enough, the model must return 2-3 candidates with uncertainty instead of forcing a single answer.
- User-facing output should include: canonical guess, visible clues, cultural/historical explanation, uncertainty, and at least two expert perspective cards.
- Hidden chain-of-thought, debug labels, raw provider traces, and phrases such as `API候选` or `命中用户核心目标` must not appear in user copy.

## Fukuoka / Kyushu

| ID | Area | Subject | Acceptable canonical terms | Must include | Failure examples |
| --- | --- | --- | --- | --- | --- |
| KYU-01 | Fukuoka | Fukuoka Tower | `Fukuoka Tower`, `福岡タワー`, `福冈塔` | tower shape, seaside/modern landmark context, photo/style hint | Calls it Tokyo Tower or generic skyscraper |
| KYU-02 | Fukuoka | Dazaifu Tenmangu | `Dazaifu Tenmangu`, `太宰府天満宮`, `太宰府天满宫` | shrine/tenmangu context, Sugawara no Michizane or learning deity if sourced | Calls it generic temple only |
| KYU-03 | Fukuoka | Kushida Shrine | `Kushida Shrine`, `櫛田神社`, `栉田神社` | Hakata cultural link, shrine architecture, Yamakasa relation if visible | Recommends random Fukuoka food places |
| KYU-04 | Fukuoka | Hakata Gion Yamakasa float/sign | `博多祇園山笠`, `Hakata Gion Yamakasa` | festival/craft/cultural explanation, visible float/sign clues | Treats it as generic parade or shop sign |
| KYU-05 | Fukuoka | Momochi Seaside Park | `Momochi Seaside Park`, `百道浜`, `シーサイドももち` | beach/waterfront clue, nearby Fukuoka Tower relation if visible | Returns only food recommendations |
| KYU-06 | Kitakyushu | Mojiko Retro | `門司港レトロ`, `Mojiko Retro` | port/retro architecture/history clues | Calls it European city without Japan uncertainty |
| KYU-07 | Oita | Beppu Jigoku | `別府地獄`, `Beppu Jigoku`, specific hell name if visible | geothermal/steam/water color clue, travel guide perspective | Calls it ordinary lake/park |
| KYU-08 | Oita | Yufuin / Kinrin Lake | `由布院`, `金鱗湖`, `Yufuin`, `Kinrin Lake` | rural onsen town/scenic clues, uncertainty if image is generic street | Overclaims exact place from a generic cafe/street |
| KYU-09 | Kumamoto | Kumamoto Castle | `熊本城`, `Kumamoto Castle` | castle architecture, stone walls, reconstruction context if sourced | Calls it Osaka Castle without counter-evidence |
| KYU-10 | Kagoshima | Sakurajima | `桜島`, `Sakurajima` | volcanic/geography clue, Kagoshima Bay if visible | Calls it Mount Fuji |

## Kansai

| ID | Area | Subject | Acceptable canonical terms | Must include | Failure examples |
| --- | --- | --- | --- | --- | --- |
| KAN-01 | Kyoto | Kiyomizu-dera | `清水寺`, `Kiyomizu-dera` | wooden stage/temple hillside clue, history/culture view | Calls it generic shrine |
| KAN-02 | Kyoto | Fushimi Inari Taisha | `伏見稲荷大社`, `Fushimi Inari Taisha` | torii gates, Inari shrine context | Treats it as generic red tunnel |
| KAN-03 | Kyoto | Kinkaku-ji | `金閣寺`, `Kinkaku-ji`, `Golden Pavilion` | golden pavilion/reflection/garden clues | Calls it Ginkaku-ji |
| KAN-04 | Kyoto | Shoren-in | `青蓮院`, `Shoren-in` | quiet temple/garden clues, hidden-gem uncertainty if image is weak | Overconfidently calls it Kiyomizu-dera |
| KAN-05 | Kyoto | Nijo Castle | `二条城`, `Nijo Castle` | castle/palace architecture, Tokugawa/Edo context if sourced | Calls it Osaka Castle |
| KAN-06 | Osaka | Osaka Castle | `大阪城`, `Osaka Castle` | castle tower/moat/stone wall clues | Calls it Himeji Castle without uncertainty |
| KAN-07 | Osaka | Dotonbori / Glico sign | `道頓堀`, `Dotonbori`, `グリコサイン` | neon/river/entertainment district clue | Returns only restaurant cards |
| KAN-08 | Nara | Todai-ji | `東大寺`, `Todai-ji` | great temple/deer/Nara context if visible | Calls it Kyoto temple only |
| KAN-09 | Uji | Byodo-in | `平等院`, `Byodo-in`, `Phoenix Hall` | phoenix hall/pond/symmetry clue | Calls it Kinkaku-ji |
| KAN-10 | Hyogo | Himeji Castle | `姫路城`, `Himeji Castle` | white castle/large complex clue | Calls it Osaka Castle |

## Output Quality Rubric

| Score | Meaning | Required evidence |
| --- | --- | --- |
| 5 | Exact and useful | Correct canonical name, visible clues, cultural/history explanation, uncertainty if relevant, perspective cards |
| 4 | Mostly correct | Correct region/entity with minor missing context |
| 3 | Plausible but incomplete | Candidate is plausible but lacks enough clue explanation or confidence notes |
| 2 | Generic | Talks about Japan/travel generally without solving the image |
| 1 | Wrong or misleading | Wrong landmark with high confidence, fabricated facts, or unrelated recommendations |

MVP pass threshold: average score >= 4.0 across the matrix, with no score 1 on iconic landmarks.
