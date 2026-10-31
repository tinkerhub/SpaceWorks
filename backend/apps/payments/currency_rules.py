"""Published provider charge currencies, captured 2026-10-30; no ISO fallback.

Stripe: https://docs.stripe.com/currencies
Three decimals: https://support.stripe.com/questions/which-payments-methods-and-products-are-available-in-the-uae
Razorpay: https://razorpay.com/docs/payments/international-payments/
Payment-link units: https://razorpay.com/docs/api/payments/payment-links/create-standard/

Stripe's 139 codes are the full SupportedPresentmentCurrencies union across 45
country lists, not the minimum-charge table. Razorpay's 128 codes and exponents
come from its Supported Currencies table. Account/country availability remains
provider-owned; a published code does not guarantee support for every account.
"""


STRIPE_TWO_DECIMAL_CURRENCIES = frozenset(
    "aed afn all amd ang aoa ars aud awg azn bam bbd bdt bmd bnd bob brl bsd "
    "bwp byn bzd cad cdf chf cny cop crc cve czk dkk dop dzd egp etb eur fjd "
    "fkp gbp gel gip gmd gtq gyd hkd hnl htg huf idr ils inr jmd kes kgs khr "
    "kyd kzt lak lbp lkr lrd lsl mad mdl mkd mmk mnt mop mur mvr mwk mxn myr "
    "mzn nad ngn nio nok npr nzd pab pen pgk php pkr pln qar ron rsd rub sar "
    "sbd scr sek sgd shp sle sos srd std szl thb tjs top try ttd twd tzs uah "
    "usd uyu uzs wst xcd xcg yer zar zmw".split()
)
STRIPE_ZERO_DECIMAL_CURRENCIES = frozenset(
    "bif clp djf gnf jpy kmf krw mga pyg rwf vnd vuv xaf xof xpf".split()
)
STRIPE_THREE_DECIMAL_CURRENCIES = frozenset("bhd jod kwd omr tnd".split())
STRIPE_LEGACY_WHOLE_CURRENCIES = frozenset("isk ugx".split())

RAZORPAY_TWO_DECIMAL_CURRENCIES = frozenset(
    "aed all amd aud awg azn bam bbd bdt bgn bmd bnd bob brl bsd btn bwp bzd "
    "cad chf cny cop crc cup cve czk dkk dop dzd egp etb eur fjd gbp ghs gip "
    "gmd gtq gyd hkd hnl hrk htg huf idr ils inr jmd kes kgs khr kyd kzt lak "
    "lkr lrd lsl mad mdl mga mkd mmk mnt mop mur mvr mwk mxn myr mzn nad ngn "
    "nio nok npr nzd pen pgk php pkr pln qar ron rsd rub sar scr sek sgd sll "
    "sos svc szl thb try ttd twd tzs uah usd uyu uzs xcd yer zar zmw".split()
)
RAZORPAY_ZERO_DECIMAL_CURRENCIES = frozenset(
    "bif clp djf gnf isk jpy kmf krw pyg rwf ugx vnd vuv xaf xof xpf".split()
)
RAZORPAY_THREE_DECIMAL_CURRENCIES = frozenset("bhd iqd jod kwd omr tnd".split())

# Values are (major-to-minor scale, allowed minor-unit quantum). Three-decimal
# quantum 10 is our two-major-decimal ledger policy, not a universal Stripe API
# restriction. Razorpay separately requires a final zero in payment-link amounts.
# Stripe lists UGX among zero-decimal currencies but its legacy x100 rule wins;
# ISK also uses x100 for whole major units. HUF/TWD charges remain two-decimal.
STRIPE_CURRENCY_UNITS = {
    **dict.fromkeys(STRIPE_TWO_DECIMAL_CURRENCIES, (100, 1)),
    **dict.fromkeys(STRIPE_ZERO_DECIMAL_CURRENCIES, (1, 1)),
    **dict.fromkeys(STRIPE_THREE_DECIMAL_CURRENCIES, (1000, 10)),
    **dict.fromkeys(STRIPE_LEGACY_WHOLE_CURRENCIES, (100, 100)),
}
RAZORPAY_CURRENCY_UNITS = {
    **dict.fromkeys(RAZORPAY_TWO_DECIMAL_CURRENCIES, (100, 1)),
    **dict.fromkeys(RAZORPAY_ZERO_DECIMAL_CURRENCIES, (1, 1)),
    **dict.fromkeys(RAZORPAY_THREE_DECIMAL_CURRENCIES, (1000, 10)),
}
PROVIDER_CURRENCY_UNITS = {
    "stripe": STRIPE_CURRENCY_UNITS,
    "razorpay": RAZORPAY_CURRENCY_UNITS,
}
SUPPORTED_CURRENCIES = frozenset(STRIPE_CURRENCY_UNITS) | frozenset(RAZORPAY_CURRENCY_UNITS)
