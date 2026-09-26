"""Read-only quality labels, shared by result summaries and integrations."""
FLAGS={'low_confidence':'识别分数低','very_short':'显示时间很短','very_long':'显示时间异常长',
       'few_frames':'仅有少量帧','high_reading_speed':'文字密度高','many_lines':'行数异常',
       'fading_frame_preserved':'淡出画面已按原图文字保留',
       'similar_neighbor_check':'与邻句相近',
       'missing_line_recovered_check':'重新识别补回短行','language_check_disagreement':'语言校验有分歧',
       'raster_check_disagreement':'图像复查有分歧','all_caps_check':'全大写复核',
       'image_verified_repair':'已根据本帧图像补识别','fragment_compacted':'相同文字短片段已合并',
       'identical_fragment_compacted':'相同文字短片段已合并'}  # Read older diagnostic records too.

def summary(counts):
    return '；'.join(f'{FLAGS.get(key,key)} {n} 条' for key,n in sorted(counts.items(),key=lambda item:-item[1]))
