import React from 'react';
import { FormattedValue } from '../types';

interface FormattedValueProps {
  data: FormattedValue | string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  align?: 'left' | 'center' | 'right';
  color?: 'default' | 'primary' | 'success' | 'warning' | 'danger';
  className?: string;
}

const FormattedValueComponent: React.FC<FormattedValueProps> = ({
  data,
  size = 'md',
  align = 'center',
  color = 'default',
  className = ''
}) => {
  // Handle fallback to simple string
  if (typeof data === 'string') {
    return (
      <span className={`${getTextClasses(size, color)} ${getAlignClass(align)} ${className}`}>
        {data}
      </span>
    );
  }

  // Handle enhanced data with separate styling
  return (
    <span className={`${getAlignClass(align)} ${className}`}>
      <span className={`${getValueClasses(size, color)} font-bold`}>
        {data.display}
      </span>
      {data.unit && (
        <span className={`${getUnitClasses(size)} text-gray-500 dark:text-gray-400 ml-1`}>
          {data.unit}
        </span>
      )}
    </span>
  );
};

function getValueClasses(size: string, color: string): string {
  const sizeClasses = {
    sm: 'text-sm',
    md: 'text-lg',
    lg: 'text-2xl',
    xl: 'text-3xl'
  };

  const colorClasses = {
    default: 'text-gray-900 dark:text-white',
    primary: 'text-blue-600 dark:text-blue-400',
    success: 'text-green-600 dark:text-green-400',
    warning: 'text-yellow-600 dark:text-yellow-400',
    danger: 'text-red-600 dark:text-red-400'
  };

  return `${sizeClasses[size as keyof typeof sizeClasses]} ${colorClasses[color as keyof typeof colorClasses]}`;
}

function getUnitClasses(size: string): string {
  const sizeClasses = {
    sm: 'text-xs',
    md: 'text-sm',
    lg: 'text-base',
    xl: 'text-lg'
  };

  return sizeClasses[size as keyof typeof sizeClasses];
}

function getTextClasses(size: string, color: string): string {
  const sizeClasses = {
    sm: 'text-sm',
    md: 'text-lg',
    lg: 'text-2xl',
    xl: 'text-3xl'
  };

  const colorClasses = {
    default: 'text-gray-900 dark:text-white',
    primary: 'text-blue-600 dark:text-blue-400',
    success: 'text-green-600 dark:text-green-400',
    warning: 'text-yellow-600 dark:text-yellow-400',
    danger: 'text-red-600 dark:text-red-400'
  };

  return `${sizeClasses[size as keyof typeof sizeClasses]} ${colorClasses[color as keyof typeof colorClasses]}`;
}

function getAlignClass(align: string): string {
  const alignClasses = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right'
  };

  return alignClasses[align as keyof typeof alignClasses];
}

export default FormattedValueComponent;