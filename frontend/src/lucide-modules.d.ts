declare module 'lucide-react/dist/esm/icons/*.js' {
  import { ComponentType, SVGProps } from 'react';
  const Icon: ComponentType<SVGProps<SVGSVGElement> & {size?:number|string}>;
  export default Icon;
}
