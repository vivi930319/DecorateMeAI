"""Use the packaged PNG renderer with Microsoft Word as the PDF backend.

No LibreOffice installation is used. PDF export and field refresh happen in
Word; the skill's canonical render_docx.py performs page rasterization.
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

skill=Path('C:/Users/isach/.codex/plugins/cache/openai-primary-runtime/documents/26.909.12148/skills/documents/render_docx.py')
spec=importlib.util.spec_from_file_location('render_docx',skill)
renderer=importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
pdf=Path(sys.argv[2]).resolve()
def word_pdf(doc_path,user_profile,convert_tmp_dir,stem,verbose=False):
    target=Path(convert_tmp_dir)/(stem+'.pdf')
    shutil.copy2(pdf,target)
    return str(target),'Microsoft Word 16 PDF export; fields refreshed before export.'
renderer.convert_to_pdf=word_pdf
poppler='C:/Users/isach/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'
os.environ['PATH']=poppler+os.pathsep+os.environ['PATH']
paths=renderer.rasterize(sys.argv[1],sys.argv[3],110,True,False)
print('RENDERED_PAGES',len(paths))
