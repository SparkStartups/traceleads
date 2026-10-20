-- The rules that link a Google place to the company running it, in the order they are tried. Each
-- candidate meets its first rule (int.candidates defines each one), and the first rule a place's
-- candidates meet decides. Only automatic links are scored; review links wait for a person.
CREATE OR REPLACE TABLE int.rules (rank, rule, tier, meaning) AS
VALUES
    (1, 'brand_and_building', 'automatic', 'same brand, registered in the same building'),
    (2, 'brand_and_activity', 'automatic', 'same brand, with an activity that fits the category'),
    (3, 'core_and_building', 'automatic', 'same name without generic words, in the same building'),
    (4, 'rare_word_on_street', 'review', 'a rare word in both names, on the same street'),
    (5, 'only_fitting_in_building', 'review', 'the only fitting company in the building');
