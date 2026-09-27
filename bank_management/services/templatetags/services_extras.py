from django import template

register = template.Library()


@register.filter
def dict_lookup(dictionary, key):
    """
    Template filter to look up a dict value by a variable key.
    Django templates can't do {{ mydict[key] }} natively when `key` is
    itself a template variable, so this fills that gap.

    Usage: {{ my_dict|dict_lookup:my_key_variable }}
    """
    if not dictionary:
        return None
    return dictionary.get(key)


DOCUMENT_TYPE_TO_FORM_FIELD = {
    'ID_PROOF': 'id_proof',
    'PAN': 'pan',
    'ADDRESS_PROOF': 'address_proof',
    'INCOME_PROOF': 'income_proof',
}


@register.filter
def to_form_field(document_type):
    """Maps a KYCDocument.document_type value (e.g. 'ID_PROOF') to the
    matching KYCDocumentUploadForm field name (e.g. 'id_proof')."""
    return DOCUMENT_TYPE_TO_FORM_FIELD.get(document_type, '')