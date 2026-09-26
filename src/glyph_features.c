#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include <string.h>
static PyObject *mask(PyObject *self,PyObject *args){
 const unsigned char *g;Py_ssize_t length;int w,h,threshold=0;
 if(!PyArg_ParseTuple(args,"y#ii|i",&g,&length,&w,&h,&threshold))return NULL;
 if(w<=0||h<=0||(Py_ssize_t)w*h!=length||length>16000000){PyErr_SetString(PyExc_ValueError,"Invalid feature image size");return NULL;}
 unsigned char *near=calloc(length,1),*binary=calloc(length,1),*seen=calloc(length,1);
 int *queue=malloc(length*sizeof(int));PyObject *result=PyBytes_FromStringAndSize(NULL,length);
 if(!near||!binary||!seen||!queue||!result){free(near);free(binary);free(seen);free(queue);Py_XDECREF(result);return PyErr_NoMemory();}
 unsigned char *out=(unsigned char*)PyBytes_AS_STRING(result);memset(out,0,length);
 double scale=w/522.;if(scale<1)scale=1;
 Py_BEGIN_ALLOW_THREADS
 if(threshold>0){
  for(int i=0;i<length;i++)binary[i]=g[i]>threshold;
 }else{
 for(int y=0;y<h;y++)for(int x=0;x<w;x++){
  int left=x>3?x-3:0,right=x+3<w?x+3:w-1;
  for(int xx=left;xx<=right;xx++)if(g[y*w+xx]<90){near[y*w+x]=1;break;}
 }
 for(int y=0;y<h;y++)for(int x=0;x<w;x++)if(g[y*w+x]>210){
  int top=y>3?y-3:0,bottom=y+3<h?y+3:h-1;
  for(int yy=top;yy<=bottom;yy++)if(near[yy*w+x]){binary[y*w+x]=1;break;}
 }
 }
 for(int start=0;start<length;start++)if(binary[start]&&!seen[start]){
  int head=0,tail=1,xmin=w,xmax=0,ymin=h,ymax=0;queue[0]=start;seen[start]=1;
  while(head<tail){
   int i=queue[head++],x=i%w,y=i/w;
   if(x<xmin)xmin=x;if(x>xmax)xmax=x;if(y<ymin)ymin=y;if(y>ymax)ymax=y;
   for(int yy=(y?y-1:0);yy<=y+1&&yy<h;yy++)for(int xx=(x?x-1:0);xx<=x+1&&xx<w;xx++){
    int n=yy*w+xx;if(binary[n]&&!seen[n]){seen[n]=1;queue[tail++]=n;}
   }
  }
  if(tail>=2&&tail<650*scale*scale&&ymax-ymin+1<35*scale&&xmax-xmin+1<50*scale)
   for(int n=0;n<tail;n++)out[queue[n]]=1;
 }
 Py_END_ALLOW_THREADS
 free(near);free(binary);free(seen);free(queue);return result;
}
static PyMethodDef methods[]={{"mask",mask,METH_VARARGS,"Return outlined-light glyph mask."},{NULL,NULL,0,NULL}};
static struct PyModuleDef module={PyModuleDef_HEAD_INIT,"glyph_features",NULL,-1,methods};
PyMODINIT_FUNC PyInit_glyph_features(void){return PyModule_Create(&module);}
