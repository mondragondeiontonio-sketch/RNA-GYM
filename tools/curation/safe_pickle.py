"""Data-only pickle opcode interpreter; NEVER executes a pickle callable.

Restricted to primitive containers and known NumPy *serialization layouts*.
GLOBAL/STACK_GLOBAL become inert tags; only validated numeric byte buffers are
converted by our own np.frombuffer implementation. No pickle.Unpickler/load,
imports from a pickle, arbitrary REDUCE, object dtype or extension opcodes.
"""
import pickletools
import re
import numpy as np

MARK=object()
ALLOWED={('numpy','dtype'),('numpy','ndarray'),('numpy.core.numeric','_frombuffer'),
         ('numpy._core.numeric','_frombuffer'),('numpy.core.multiarray','_reconstruct'),
         ('numpy._core.multiarray','_reconstruct')}


def decode(data,max_bytes=64*1024*1024):
    if len(data)>max_bytes:raise ValueError('PICKLE_BYTE_BUDGET')
    stack=[];memo={}
    def popmark():
        at=len(stack)-1
        while at>=0 and stack[at] is not MARK:at-=1
        if at<0:raise ValueError('MISSING_MARK')
        values=stack[at+1:];del stack[at:];return values
    def array(buffer,dtype,shape,order='C'):
        if not isinstance(dtype,dict) or dtype.get('tag')!='dtype':raise ValueError('UNSAFE_DTYPE')
        name=dtype['name'];endian=dtype.get('endian','=')
        if not re.fullmatch(r'[biuf][1248]',name) or endian not in '<>=|':raise ValueError('NON_NUMERIC_DTYPE')
        if not isinstance(buffer,(bytes,bytearray)) or not isinstance(shape,tuple):raise ValueError('UNSAFE_ARRAY_LAYOUT')
        total=1
        for n in shape:
            if type(n) is not int or n<0:raise ValueError('BAD_SHAPE')
            total*=n
        dt=np.dtype(endian+name)
        if total*dt.itemsize!=len(buffer) or len(buffer)>max_bytes:raise ValueError('ARRAY_SIZE_MISMATCH')
        if order not in ('C','F'):raise ValueError('BAD_ORDER')
        return np.frombuffer(buffer,dtype=dt).reshape(shape,order=order).copy()
    for op,arg,_ in pickletools.genops(data):
        name=op.name
        if name in ('PROTO','FRAME'):continue
        if name=='STOP':
            if len(stack)!=1:raise ValueError('INVALID_FINAL_STACK')
            return stack[0]
        if name=='MARK':stack.append(MARK)
        elif name=='EMPTY_LIST':stack.append([])
        elif name=='EMPTY_TUPLE':stack.append(())
        elif name=='EMPTY_DICT':stack.append({})
        elif name=='NONE':stack.append(None)
        elif name=='NEWTRUE':stack.append(True)
        elif name=='NEWFALSE':stack.append(False)
        elif name in ('BININT','BININT1','BININT2','INT','LONG','LONG1','LONG4','FLOAT','BINFLOAT',
                       'UNICODE','BINUNICODE','SHORT_BINUNICODE','BINUNICODE8','BINBYTES','SHORT_BINBYTES','BINBYTES8','BYTEARRAY8'):
            stack.append(arg)
        elif name=='MEMOIZE':memo[len(memo)]=stack[-1]
        elif name in ('BINPUT','LONG_BINPUT','PUT'):memo[int(arg)]=stack[-1]
        elif name in ('BINGET','LONG_BINGET','GET'):stack.append(memo[int(arg)])
        elif name=='TUPLE':stack.append(tuple(popmark()))
        elif name in ('TUPLE1','TUPLE2','TUPLE3'):
            n=int(name[-1]);values=tuple(stack[-n:]);del stack[-n:];stack.append(values)
        elif name=='APPENDS':
            values=popmark()
            if type(stack[-1]) is not list:raise ValueError('APPENDS_NON_LIST')
            stack[-1].extend(values)
        elif name=='APPEND':
            value=stack.pop()
            if type(stack[-1]) is not list:raise ValueError('APPEND_NON_LIST')
            stack[-1].append(value)
        elif name in ('SETITEM','SETITEMS'):
            values=popmark() if name=='SETITEMS' else [stack.pop(-2),stack.pop()]
            if type(stack[-1]) is not dict or len(values)%2:raise ValueError('UNSAFE_SETITEMS')
            for i in range(0,len(values),2):stack[-1][values[i]]=values[i+1]
        elif name in ('GLOBAL','STACK_GLOBAL'):
            if name=='GLOBAL':module,attribute=arg.split(' ',1)
            else:
                attribute=stack.pop();module=stack.pop()
            if (module,attribute) not in ALLOWED:raise ValueError('FORBIDDEN_GLOBAL:'+str((module,attribute)))
            stack.append(('INERT_GLOBAL',module,attribute))
        elif name=='REDUCE':
            args=stack.pop();tag=stack.pop()
            if not isinstance(tag,tuple) or tag[:1]!=('INERT_GLOBAL',):raise ValueError('FORBIDDEN_REDUCE')
            if tag[2]=='dtype':
                if not isinstance(args,tuple) or not args or not re.fullmatch(r'[biuf][1248]',args[0]):raise ValueError('UNSAFE_DTYPE_REDUCE')
                stack.append({'tag':'dtype','name':args[0]})
            elif tag[2]=='_frombuffer':stack.append(array(*args))
            elif tag[2]=='_reconstruct':
                if args[0]!=('INERT_GLOBAL','numpy','ndarray') or args[1]!=(0,):raise ValueError('UNSAFE_RECONSTRUCT')
                stack.append({'tag':'array_placeholder'})
            else:raise ValueError('FORBIDDEN_CALLABLE_TAG')
        elif name=='BUILD':
            state=stack.pop();obj=stack[-1]
            if type(obj) is not dict:raise ValueError('FORBIDDEN_BUILD')
            if obj.get('tag')=='dtype':
                if not isinstance(state,tuple) or len(state)!=8 or state[1] not in '<>=|' or any(x is not None for x in state[2:5]):raise ValueError('UNSAFE_DTYPE_STATE')
                obj['endian']=state[1]
            elif obj.get('tag')=='array_placeholder':
                if len(state)!=5 or state[0]!=1:raise ValueError('UNSAFE_ARRAY_STATE')
                replacement=array(state[4],state[2],state[1],'F' if state[3] else 'C')
                for k,v in memo.items():
                    if v is obj:memo[k]=replacement
                stack[-1]=replacement
            else:raise ValueError('FORBIDDEN_BUILD_TAG')
        else:raise ValueError('UNSUPPORTED_DATA_OPCODE:'+name)
    raise ValueError('NO_STOP')
