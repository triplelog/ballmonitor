/* MathZetta 1.0.0 esm — MIT licence — https://mathzetta.com */
import{i as t,t as r}from"./chunks/core.js";import{t as m}from"./chunks/mathml.js";function s(t){const{id:r,...m}=t;return"op"===m.type?{...m,args:m.args.map(s)}:m}function n(n,o={}){if(t(n))return"<math><mi>empty</mi></math>";const i=r(n);return m(!1===o.ids?s(i):i)}export{n as toMathML};
