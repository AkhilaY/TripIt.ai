import importlib.util, sys
def load(p):
    spec=importlib.util.spec_from_file_location(p[:-3], p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
d1=load('draw.py'); d2=load('draw2.py')
scenes=[('london',d1.london),('newyork',d1.nyc),('paris',d2.paris),('amalfi',d2.amalfi),('dubai',d1.dubai)]
out=['// Generated from the scene drawings (scratchpad scenes2/gen.py): one drawing step per line, read by SceneScript.',
     '// Do not edit by hand; change the drawing and regenerate.','','enum SceneScripts {']
total=0
for name,f in scenes:
    sc=f(); script=sc.script(); total+=len(script)
    out.append(f'    static let {name} = """')
    out.append(script)
    out.append('"""')
    print(name, len(sc.ops), 'ops', len(script)//1024, 'KB')
out.append('}')
open('SceneScripts.swift','w').write('\n'.join(out)+'\n')
print('total KB', total//1024)
