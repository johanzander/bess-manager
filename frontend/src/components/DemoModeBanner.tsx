import { Eye } from 'lucide-react';

interface DemoModeBannerProps {
  onGoLive: () => void;
}

export default function DemoModeBanner({ onGoLive }: DemoModeBannerProps) {
  return (
    <div className="bg-blue-900/30 border-b border-blue-700 px-4 py-2 flex items-center justify-between">
      <div className="flex items-center gap-2 text-sm">
        <Eye className="h-4 w-4 text-blue-400" />
        <span className="font-medium text-blue-300">Demo Mode</span>
        <span className="text-gray-500">—</span>
        <span className="text-gray-400">Optimization is running but not controlling your inverter</span>
      </div>
      <button
        onClick={onGoLive}
        className="px-3 py-1 text-xs font-medium text-white bg-blue-600 rounded-md hover:bg-blue-500"
      >
        Go Live
      </button>
    </div>
  );
}
