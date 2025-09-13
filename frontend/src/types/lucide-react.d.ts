declare module 'lucide-react' {
  import { FC } from 'react';
  
  interface IconProps {
    className?: string;
    size?: number;
  }
  
  export const CheckCircle: FC<IconProps>;
  export const XCircle: FC<IconProps>;
  export const AlertCircle: FC<IconProps>;
  export const ChevronDown: FC<IconProps>;
  export const ChevronUp: FC<IconProps>;
}