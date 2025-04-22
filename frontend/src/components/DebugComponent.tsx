import React, { useEffect } from 'react';

const DebugComponent: React.FC = () => {
  useEffect(() => {
    console.log('DebugComponent mounted');
    
    // Test fetch to API
    const testApi = async () => {
      try {
        console.log('Testing API fetch...');
        const res = await fetch('/api/settings/battery');
        console.log('API test result:', {
          status: res.status,
          ok: res.ok,
          statusText: res.statusText
        });
        
        if (res.ok) {
          const data = await res.json();
          console.log('API data:', data);
        }
      } catch (err) {
        console.error('API test error:', err);
      }
    };
    
    testApi();
  }, []);

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      padding: '20px',
      background: 'red',
      color: 'white',
      zIndex: 9999,
      textAlign: 'center'
    }}>
      Debug Component Rendering - Check Console
    </div>
  );
};

export default DebugComponent;