"""BIST hisse evreni — yfinance canlı çekim için (.IS suffix eklenir)."""

BIST_TICKERS = [
    'AAGYO', 'ACSEL', 'ADEL', 'ADESE', 'ADGYO', 'AEFES', 'AFYON', 'AGESA',
    'AGHOL', 'AGROT', 'AGYO', 'AHGAZ', 'AHSGY', 'AKBNK', 'AKCNS', 'AKENR',
    'AKFGY', 'AKFIS', 'AKFYE', 'AKGRT', 'AKMGY', 'AKSA', 'AKSEN', 'ALARK',
    'ALBRK', 'ALCAR', 'ALCTL', 'ALFAS', 'ALGYO', 'ALKA', 'ALKIM', 'ALKLC',
    'ALTNY', 'ALVES', 'ANEL', 'ANGEN', 'ANHYT', 'ANSGR', 'ARASE', 'ARCLK',
    'ARDYZ', 'ARENA', 'ARMGD', 'ARSAN', 'ARTMS', 'ARZUM', 'ASELS', 'ASGYO',
    'ASTOR', 'ASUZU', 'ATAGY', 'ATAKP', 'ATATP', 'ATATR', 'ATEKS', 'ATLAS',
    'ATSYH', 'AVGYO', 'AVHOL', 'AVPGY', 'AYCES', 'AYDEM', 'AYEN', 'AYGAZ',
    'AZTEK', 'BAGFS', 'BALSU', 'BANVT', 'BASGZ', 'BAYRK', 'BEYAZ', 'BIMAS',
    'BIOEN', 'BIZIM', 'BMSCH', 'BNTAS', 'BOBET', 'BORLS', 'BORSK', 'BOSSA',
    'BRISA', 'BRKVY', 'BRSAN', 'BRYAT', 'BSOKE', 'BTCIM', 'BUCIM', 'BURCE',
    'BVSAN', 'CANTE', 'CCOLA', 'CEMAS', 'CEMTS', 'CGCAM', 'CIMSA', 'CLEBI',
    'CMBTN', 'CONSE', 'CRDFA', 'CRFSA', 'CVKMD', 'CWEN', 'DARDL', 'DENGE',
    'DEVA', 'DGGYO', 'DOAS', 'DOFRB', 'DOGUB', 'DOHOL', 'DOKTA', 'DSTKF',
    'DYOBY', 'EBEBEK', 'ECILC', 'ECZYT', 'EGEEN', 'EGGUB', 'EGPRO', 'EGSER',
    'EKGYO', 'EMNIS', 'ENERY', 'ENJSA', 'ENKAI', 'ERCB', 'EREGL', 'ESCAR',
    'EUPWR', 'FROTO', 'FZLGY', 'GARAN', 'GEDIK', 'GENIL', 'GEREL', 'GIPTA',
    'GLRMK', 'GUBRF', 'HALKB', 'HEDEF', 'HEKTS', 'HTTBT', 'HURGZ', 'ICBTC',
    'IEYHO', 'IHAAS', 'INDES', 'INFO', 'ISCTR', 'ISDMR', 'IZENR', 'KAREL',
    'KARSN', 'KAYSE', 'KBORU', 'KCHOL', 'KLGYO', 'KLKIM', 'KLMSN', 'KLSER',
    'KONTR', 'KONYA', 'KOTON', 'KRDMA', 'KRDMB', 'KRDMD', 'KTLEV', 'KTSKR',
    'KUTPO', 'KUYAS', 'LILAK', 'MAGEN', 'MANAS', 'MAVI', 'MGROS', 'MIATK',
    'MOBTL', 'MPARK', 'MTRKS', 'NETAS', 'NETCD', 'NTGAZ', 'OBAMS', 'ODAS',
    'ODINE', 'OTKAR', 'OYAKC', 'OZKGY', 'PAHOL', 'PAPIL', 'PATEK', 'PEKGY',
    'PENGD', 'PENTA', 'PETKM', 'PGSUS', 'POLHO', 'QNBTR', 'RAYSG', 'REEDER',
    'RYSAS', 'SAHOL', 'SARKY', 'SASA', 'SAYAS', 'SDTTR', 'SELEC', 'SISE',
    'SMRTG', 'SOKM', 'TABGD', 'TATGD', 'TAVHL', 'TBORG', 'TCELL', 'TEHOL',
    'TERA', 'THYAO', 'TKFEN', 'TKNSA', 'TKSB', 'TMSN', 'TOASO', 'TRALT',
    'TRGYO', 'TRILC', 'TTKOM', 'TTRAK', 'TUPRS', 'TURSG', 'ULKER', 'VAKBN',
    'VAKKO', 'VBTYZ', 'VESBE', 'VESTL', 'YEOTK', 'YKBNK', 'ZOREN', 'ZRGYO',
]

def yahoo_symbols():
    """Yahoo Finance sembolleri (BIST = .IS suffix)."""
    return [t + ".IS" for t in BIST_TICKERS]
