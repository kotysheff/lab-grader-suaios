"""Render saved research tables. Does not run simulations."""
import csv
import importlib.metadata
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

LABELS={'deadline':'Просроченные сначала','chance_5':'Порог 5','score':'Текущий балл',
        'random':'Случайная очередь','fifo':'FIFO','chance_4':'Порог 4'}
COLORS={'deadline':'#cc6b46','chance_5':'#a867a6','score':'#b79536',
        'random':'#628bb4','fifo':'#427e80','chance_4':'#25845c'}


def draw(folder, assets):
    folder,assets=Path(folder),Path(assets);assets.mkdir(exist_ok=True)
    summary=json.loads((folder/'summary.json').read_text())
    policies=list(summary['policies']);n=summary['runs']*summary['config']['students']
    hist={}
    for policy in policies:
        with (folder/policy/'histogram.csv').open() as file:
            hist[policy]=[int(r['count']) for r in csv.DictReader(file)]
        assert len(hist[policy])==51 and sum(hist[policy])==n
    with (folder/'per_run.csv').open() as file:runs=list(csv.DictReader(file))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,
        'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#b7c4ca',
        'axes.labelcolor':'#263e4a','text.color':'#193543','xtick.color':'#51646f',
        'ytick.color':'#51646f','svg.fonttype':'none','figure.facecolor':'white'})
    subtitle=f"{summary['runs']:,} общих сценариев · {summary['config']['students']} студентов · 20 мест · seed {summary['seed']}".replace(',',' ')
    def save(fig,name):
        for ext in ['png','svg']:fig.savefig(assets/f'{name}.{ext}',dpi=170,bbox_inches='tight',pad_inches=.2)
        svg=assets/f'{name}.svg'
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
        plt.close(fig)
    def style(ax):
        ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    ranking=sorted(policies,key=lambda p:summary['policies'][p]['four_five_per_group'],reverse=True)
    fig,axes=plt.subplots(1,2,figsize=(14,5.5),gridspec_kw={'width_ratios':[1.3,1]})
    fig.suptitle('Какая очередь даёт больше оценок 4–5?',fontsize=21,fontweight='bold',y=1.05)
    fig.text(.5,.98,subtitle,ha='center',color='#637985')
    values=[summary['policies'][p]['four_five_per_group'] for p in ranking]
    bars=axes[0].barh([LABELS[p] for p in ranking],values,color=[COLORS[p] for p in ranking])
    axes[0].invert_yaxis();axes[0].set_xlim(0,20)
    axes[0].bar_label(bars,labels=[f'{v:.3f}' for v in values],padding=5)
    axes[0].set_xlabel('Среднее число студентов с 4–5 в группе из 30')
    diff=[p for p in ranking if p!='fifo']
    for i,p in enumerate(diff):
        d=summary['paired_difference_vs_fifo'][p];lo,hi=d['mc_95_interval']
        axes[1].errorbar(d['mean_difference'],i,xerr=[[d['mean_difference']-lo],[hi-d['mean_difference']]],
                         fmt='o',color=COLORS[p],capsize=5,markersize=8)
    axes[1].axvline(0,color='#84949e',ls='--',lw=1)
    axes[1].set_yticks(range(len(diff)),[LABELS[p] for p in diff]);axes[1].invert_yaxis()
    axes[1].set_xlabel('Разница с FIFO · 95% интервал Монте-Карло')
    for ax in axes:style(ax)
    fig.tight_layout();save(fig,'comparison')

    fig,axes=plt.subplots(3,2,figsize=(14,11),sharex=True,sharey=True)
    fig.suptitle('Распределение итоговых баллов',fontsize=23,fontweight='bold',y=1.01)
    fig.text(.5,.975,subtitle,ha='center',color='#637985')
    for ax,p in zip(axes.flat,policies):
        ax.axvspan(32.5,50.5,color='#edf6ef')
        ax.bar(range(51),hist[p],color=COLORS[p],width=.9)
        ax.set_title(LABELS[p],loc='left',fontweight='bold');ax.set_xlim(-1,51)
        ax.set_ylabel('Студентов');ax.set_xlabel('Баллы, 0–50');style(ax)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x,_:f'{x:,.0f}'.replace(',',' ')))
    fig.tight_layout(rect=(0,0,1,.95));save(fig,'scores')

    fig,ax=plt.subplots(figsize=(13,5.5));left=np.zeros(len(ranking))
    for grade,color in [(2,'#c2cbd1'),(3,'#e9c77f'),(4,'#7cbaa4'),(5,'#2f7f69')]:
        vals=np.array([summary['policies'][p]['totals'][f'grade_{grade}']/n*100 for p in ranking])
        ax.barh([LABELS[p] for p in ranking],vals,left=left,color=color,label=str(grade))
        for i,v in enumerate(vals):
            if v>4:ax.text(left[i]+v/2,i,f'{v:.1f}%',ha='center',va='center',color='white' if grade==5 else '#263e4a')
        left+=vals
    ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xlabel('Доля студентов, %')
    ax.set_title('Какие оценки получают студенты',loc='left',fontsize=21,fontweight='bold',pad=25)
    ax.legend(title='Оценка',loc='upper center',bbox_to_anchor=(.5,-.14),ncol=4,frameon=False)
    fig.tight_layout();save(fig,'grades')

    fig,axes=plt.subplots(1,3,figsize=(16,5))
    for ax,key,label in zip(axes,['mean','median','std'],['Средний балл группы','Медиана группы','СКО группы']):
        all_values=[float(r[key]) for r in runs]
        bins=np.linspace(min(all_values),max(all_values),41)
        for p in policies:
            ax.hist([float(r[key]) for r in runs if r['policy']==p],bins=bins,
                    histtype='step',lw=1.4,label=LABELS[p],color=COLORS[p])
        ax.set_xlabel(label);ax.set_ylabel('Прогонов');style(ax)
    fig.suptitle('Как различаются группы между прогонами',fontsize=21,fontweight='bold',y=1.12)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='upper center',bbox_to_anchor=(.5,1.05),ncol=3,frameon=False)
    fig.tight_layout();save(fig,'run-statistics')
    env={'python':sys.version.split()[0],**{p:importlib.metadata.version(p) for p in ['numpy','pandas','matplotlib']}}
    (folder.parent/'environment.json').write_text(json.dumps(env,indent=2)+'\n')
    print('Saved 4 PNG + 4 SVG charts; dependency versions:',env)


if __name__=='__main__':draw(sys.argv[1],sys.argv[2])
