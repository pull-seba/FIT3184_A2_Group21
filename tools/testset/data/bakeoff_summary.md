# Rekognition bake-off

Recall = share of that species' images where the tag was found. False = images of something else that got this tag.

## Threshold sweep

| Tag | 50 | 55 | 60 | 65 | 70 | 75 | 80 | 85 | 90 | 95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cane toad (recall / false) | 95% / 8 | 95% / 2 | 95% / 1 | 90% / 1 | 90% / 0 | 85% / 0 | 80% / 0 | 70% / 0 | 65% / 0 | 40% / 0 |
| cat (recall / false) | 62% / 15 | 56% / 3 | 56% / 2 | 56% / 2 | 56% / 2 | 56% / 2 | 56% / 2 | 56% / 1 | 56% / 0 | 38% / 0 |
| dog (recall / false) | 94% / 22 | 94% / 13 | 94% / 12 | 94% / 12 | 94% / 11 | 94% / 9 | 94% / 8 | 94% / 6 | 94% / 6 | 88% / 3 |
| feral pig (recall / false) | 82% / 14 | 82% / 7 | 82% / 7 | 82% / 7 | 82% / 7 | 82% / 7 | 82% / 7 | 82% / 7 | 65% / 5 | 65% / 4 |
| fox (recall / false) | 90% / 48 | 80% / 20 | 75% / 6 | 70% / 6 | 60% / 5 | 60% / 5 | 55% / 4 | 50% / 1 | 50% / 1 | 45% / 1 |
| rabbit (recall / false) | 100% / 21 | 100% / 6 | 89% / 4 | 83% / 4 | 83% / 2 | 83% / 2 | 83% / 2 | 78% / 2 | 78% / 1 | 56% / 1 |

## At the suggested per-tag thresholds

Chosen per tag to maximise correct - 1 x false tags (ties go to the higher threshold).

| Tag | Threshold | Images | Recall | Count exact | Recall clear | Recall night | Recall other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cane toad | 70 | 20 | 90% | 83% | 92% | - | 86% |
| cat | 90 | 16 | 56% | 89% | 100% | 25% | 33% |
| dog | 95 | 17 | 88% | 93% | 100% | - | 67% |
| feral pig | 95 | 17 | 65% | 73% | 60% | 100% | 60% |
| fox | 90 | 20 | 50% | 80% | 100% | 71% | 20% |
| rabbit | 90 | 18 | 78% | 86% | 100% | - | 67% |

- Negative images given a target tag: 4 of 32 (neg_wombat_002: feral pig, neg_wombat_005: feral pig, neg_wombat_008: feral pig, neg_hare_008: rabbit)
- Images with no mapped tag but a fallback label (Frog, Amphibian, Hare, Canine): 45
- Target images missed: 31

## Misses (top Rekognition labels)

- fox/fox_002.jpg (night): Animal 90, Coyote 90, Mammal 90, Deer 88, Wildlife 88
- fox/fox_004.jpg (other): Plant 99, Vegetation 99, Tree 97, Grass 94, Animal 93
- fox/fox_005.jpg (other): Soil 100, Animal 85, Mammal 84, Bird 78, Wildlife 73
- fox/fox_006.jpg (other): Countryside 100, Farm 100, Field 100, Grassland 100, Nature 100
- fox/fox_007.jpg (other): Road 100, Tarmac 100, Gravel 98, City 93, Street 93
- fox/fox_008.jpg (other): Architecture 100, Building 100, Outdoors 100, Shelter 100, Grass 99
- fox/fox_009.jpg (other): Animal 100, Zoo 100, Plant 91, Vegetation 91, Mammal 79
- fox/fox_011.jpg (night): Animal 100, Coyote 100, Mammal 100, Plant 97, Vegetation 97
- fox/fox_018.jpg (other): Soil 97, Gravel 88, Road 88, Animal 72, Bird 72
- cat/cat_001.jpg (other): Tin 98, Can 94, Trash Can 92, Road 57, Handrail 55
- cat/cat_002.jpg (night): Nature 95, Night 95, Outdoors 95, Animal 87, Coyote 87
- cat/cat_006.jpg (night): Outdoors 92, Animal 88, Mammal 88, Nature 84, Canine 72
- cat/cat_008.jpeg (other): Rubble 100, Nature 100, Outdoors 100, Pond 100, Water 100
- cat/cat_011.jpeg (other): Nature 100, Outdoors 100, Weather 100, Night 100, Fog 58
- cat/cat_015.jpg (other): Outdoors 100, Nature 98, Weather 87, Head 77, Person 77
- cat/cat_018.jpg (night): Baby 99, Person 99, Outdoors 82, Head 76, Animal 75
- dog/dog_004.jpg (other): Animal 100, Coyote 100, Mammal 100, Pig 91, Wolf 57
- dog/dog_011.jpg (other): Grass 98, Plant 98, Animal 95, Coyote 95, Mammal 95
- rabbit/rabbit_004.jpg (other): Clothing 100, Footwear 100, Shoe 100, Sneaker 100, Soil 99
- rabbit/rabbit_005.jpeg (other): Animal 100, Bird 100, Blackbird 100, Plant 99, Vegetation 99
- rabbit/rabbit_014.jpg (other): Animal 98, Hare 98, Mammal 98, Rodent 98, Plant 87
- feral_pig/feral_pig_007.jpg (other): Jungle 100, Nature 100, Outdoors 100, Plant 100, Vegetation 100
- feral_pig/feral_pig_012.jpg (other): Clothing 100, Glove 100, Footwear 100, Shoe 100, Wood 100
- feral_pig/feral_pig_014.jpg (clear): Plant 100, Vegetation 100, Land 99, Nature 99, Outdoors 99
- feral_pig/feral_pig_015.jpeg (clear): Jungle 100, Nature 100, Outdoors 100, Plant 100, Vegetation 100
- feral_pig/feral_pig_016.jpg (other): Plant 100, Vegetation 100, Animal 99, Zoo 99, Soil 91
- feral_pig/feral_pig_017.jpg (other): Plant 100, Tree 100, Tree Stump 100, Animal 84, Canine 84
- cane_toad/cane_toad_003.jpeg (clear): Amphibian 99, Animal 99, Frog 99, Wildlife 99, Insect 95
- cane_toad/cane_toad_016.jpg (other): Plant 100, Tree 100, Wood 100, Soil 100, Tree Stump 92
- fox/fox_019.jpg (other): Animal 94, Wildlife 94, Mammal 91, Dinosaur 87, Reptile 87
- rabbit/rabbit_019.jpg (other): Animal 95, Kangaroo 95, Mammal 95, Bird 93, Outdoors 76

## Counting: own boxes vs borrowed boxes

Search counts are minimums: `{"fox": 2}` matches any photo tagged fox with count 2 or more. *Finds 2+* = photos with 2+ animals where that query would match. *Over* = count above the truth (it would match queries it shouldn't).

| Tag | Photos with 2+ | Own: exact | Own: finds 2+ | Borrowed: exact | Borrowed: finds 2+ | Over, all photos (own / borrowed) |
| --- | --- | --- | --- | --- | --- | --- |
| cane toad | 3 | 0% | 0% | 0% | 33% | 0 / 0 |
| cat | 1 | 0% | 0% | 0% | 0% | 0 / 0 |
| dog | 1 | 0% | 0% | 0% | 0% | 0 / 0 |
| feral pig | 4 | 25% | 50% | 75% | 100% | 0 / 0 |
| fox | 3 | 0% | 0% | 67% | 67% | 0 / 0 |
| rabbit | 3 | 0% | 0% | 0% | 33% | 0 / 1 |

Photos with 2+ animals (true / own / borrowed):

- cat/cat_013.jpg: 2 / 1 / 1
- dog/dog_013.jpg: 2 / 1 / 1
- rabbit/rabbit_018.jpeg: 2 / 1 / 1
- feral_pig/feral_pig_001.jpg: 4 / 2 / 2
- feral_pig/feral_pig_002.jpg: 2 / 1 / 2
- feral_pig/feral_pig_004.jpg: 2 / 2 / 2
- feral_pig/feral_pig_009.jpg: 2 / 1 / 2
- fox/fox_019.jpg: 2 / 0 / 0
- fox/fox_020.jpg: 2 / 1 / 2
- fox/fox_021.jpg: 2 / 1 / 2
- cane_toad/cane_toad_019.jpg: 3 / 1 / 1
- cane_toad/cane_toad_020.jpg: 6 / 1 / 2
- cane_toad/cane_toad_021.jpg: 2 / 1 / 1
- rabbit/rabbit_019.jpg: 12 / 0 / 0
- rabbit/rabbit_020.jpg: 11 / 1 / 7
