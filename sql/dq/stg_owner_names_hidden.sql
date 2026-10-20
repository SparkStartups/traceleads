-- The register hides the name of a company named after its owner (IĮ): its name is the legal
-- form's own, "Individuali įmonė". Another name may be the owner's, so the build stops. The rows
-- give only the company code, so the result holds no name.
SELECT jar.ja_kodas
FROM stg.jar_entities AS jar
JOIN ref.legal_forms AS forms ON forms.code = jar.legal_form
WHERE jar.snapshot_month = getvariable('snapshot_month')
    AND forms.named_after_owner
    AND jar.legal_name <> forms.name
