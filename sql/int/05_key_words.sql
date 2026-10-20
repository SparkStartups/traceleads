-- The words the name keys drop, from the configuration in ref, as plain text like the keys: the
-- words of the legal forms ('uab', 'uzdaroji', ...) and the generic words ('kavine', 'vilniaus',
-- ...). A lambda cannot hold the subqueries behind them, so the models join this one row.
CREATE OR REPLACE TABLE int.key_words AS
SELECT
    (
        SELECT list(DISTINCT word ORDER BY word)
        FROM (
            SELECT unnest(string_split(int.plain_text(abbreviation || ' ' || name), ' ')) AS word
            FROM ref.legal_forms
        )
    ) AS form_words,
    (
        SELECT list(DISTINCT int.plain_text(word) ORDER BY int.plain_text(word))
        FROM ref.generic_words
    ) AS generic_words;
