"""Repeatable quality report; requires a manually verified reference, never self-grades OCR confidence."""
import argparse,json
from pathlib import Path
from difflib import SequenceMatcher

def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=row
    return previous[-1]

def evaluate(reference,result,timing_only=False):
    a=reference['events'];b=result['events'];at=[' '.join(e['text'].split()) for e in a];bt=[' '.join(e['text'].split()) for e in b]
    matches=list(SequenceMatcher(None,at,bt,autojunk=False).get_matching_blocks());matched=sum(m.size for m in matches);errors=[]
    for m in matches:
        for offset in range(m.size):
            x,y=a[m.a+offset],b[m.b+offset];errors.extend([abs(x['start']-y['start']),abs(x['end']-y['end'])])
    errors.sort();ra='\n'.join(at);rb='\n'.join(bt)
    import statistics
    # Counts actual exported cues, never internal OCR groups. Overlap may also
    # reflect incorrect timing, so it is not a stand-alone accuracy score.
    counts=[sum(min(x['end'],y['end'])-max(x['start'],y['start'])>.02 for y in b) for x in a]
    return {'reference_cues':len(a),'output_cues':len(b),'exact_text_matched_cues':None if timing_only else matched,'unmatched_reference_cues':None if timing_only else len(a)-matched,'unmatched_output_cues':None if timing_only else len(b)-matched,'character_error_rate':None if timing_only else round(distance(ra,rb)/max(1,len(ra)),6),'matched_boundary_p95_seconds':errors[min(len(errors)-1,int(len(errors)*.95))] if errors and not timing_only else None,'matched_boundary_max_seconds':max(errors,default=None) if not timing_only else None,'overlap_fragments_per_reference_mean':round(statistics.mean(counts),3) if counts else 0,'overlap_fragments_per_reference_median':statistics.median(counts) if counts else 0,'reference_cues_without_temporal_overlap':counts.count(0),'performance':result.get('performance',{}),'scope':'Only this reference/video pair. Text metrics require manually verified same-language reference. Overlap fragments count exported cues, not OCR groups; timing-only mode disables text comparisons.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('reference',type=Path);parser.add_argument('result',type=Path);parser.add_argument('--timing-only',action='store_true');parser.add_argument('-o','--output',type=Path,required=True);a=parser.parse_args();report=evaluate(json.loads(a.reference.read_text(encoding='utf-8')),json.loads(a.result.read_text(encoding='utf-8')),a.timing_only);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
