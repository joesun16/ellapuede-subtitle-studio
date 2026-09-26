"""Explicit, bundled recognition model for every exposed portable language."""

ROUTES={
    'ch_v6':{'det':'PP-OCRv6_det_small.onnx','det_version':'PPOCRV6','det_type':'SMALL',
             'rec':'PP-OCRv6_rec_small.onnx','rec_version':'PPOCRV6','rec_type':'SMALL','script':'ch'},
    'en_v5':{'det':'ch_PP-OCRv5_det_mobile.onnx','det_version':'PPOCRV5','det_type':'MOBILE',
             'rec':'en_PP-OCRv5_rec_mobile.onnx','rec_version':'PPOCRV5','rec_type':'MOBILE','script':'en'},
    'ko_v5':{'det':'PP-OCRv6_det_small.onnx','det_version':'PPOCRV6','det_type':'SMALL',
             'rec':'korean_PP-OCRv5_rec_mobile.onnx','rec_version':'PPOCRV5','rec_type':'MOBILE','script':'korean'},
    'th_v5':{'det':'PP-OCRv6_det_small.onnx','det_version':'PPOCRV6','det_type':'SMALL',
             'rec':'th_PP-OCRv5_rec_mobile.onnx','rec_version':'PPOCRV5','rec_type':'MOBILE','script':'th'},
    'latin_v5':{'det':'PP-OCRv6_det_small.onnx','det_version':'PPOCRV6','det_type':'SMALL',
                'rec':'latin_PP-OCRv5_rec_mobile.onnx','rec_version':'PPOCRV5','rec_type':'MOBILE','script':'latin'},
    'ja_v4':{'det':'PP-OCRv6_det_small.onnx','det_version':'PPOCRV6','det_type':'SMALL',
             'rec':'japan_PP-OCRv4_rec_mobile.onnx','rec_version':'PPOCRV4','rec_type':'MOBILE','script':'japan'},
    'cht_v4':{'det':'PP-OCRv6_det_small.onnx','det_version':'PPOCRV6','det_type':'SMALL',
              'rec':'chinese_cht_PP-OCRv3_rec_mobile.onnx','rec_version':'PPOCRV4','rec_type':'MOBILE','script':'chinese_cht'},
}

LANGUAGE_ROUTES={'auto':'ch_v6','zh-Hans':'ch_v6','en-US':'en_v5','ko-KR':'ko_v5','th-TH':'th_v5',
                 'zh-Hant':'cht_v4','ja-JP':'ja_v4','es-ES':'latin_v5','fr-FR':'latin_v5',
                 'de-DE':'latin_v5','pt-BR':'latin_v5','it-IT':'latin_v5'}

def select_route(languages):
    codes=list(languages)
    if codes==['zh-Hans','en-US']:return 'ch_v6'
    if len(codes)==1 and codes[0] in LANGUAGE_ROUTES:return LANGUAGE_ROUTES[codes[0]]
    raise ValueError('当前离线模型不支持该语言组合；请只选择列表中的一种原语言。')
