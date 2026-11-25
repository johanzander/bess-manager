import React from 'react';
import { PerformanceResult } from '../../types';

/** Which expected quarters the comparison could use, and why the rest were left out. */
const CoverageTable: React.FC<{ data: PerformanceResult }> = ({ data }) => {
  const c = data.coverage;
  const rows = [
    [
      'Energy quarters',
      `${c.actualPeriods} actual; ${c.predictedPeriods} predicted; ${c.missingPeriods} missing`,
      `${c.analyzedPeriods}/${c.expectedPeriods} analyzed`,
    ],
    [
      'Recording artefacts',
      `${c.restartPlaceholders} zero-filled restart quarters`,
      `${c.socDropouts} quarters with SOC recorded as 0 % (shown as unknown)`,
    ],
    ['Backup use', `${c.belowReservePeriods} quarters below the reserve`, 'Left out of both sides'],
    [
      'Invalid records',
      `${c.invalidRecords} invalid`,
      `${c.excludedIntervals.length} quarters excluded in total`,
    ],
    [
      'Hindsight model',
      data.status === 'unsupported_model'
        ? 'Rejected by physical model checks'
        : data.comparison
          ? 'Passed physical model checks'
          : 'Not run',
      data.comparison?.executionReplayed
        ? 'Inverter execution replayed'
        : 'Inverter execution not modelled',
    ],
  ];
  return (
    <div className="overflow-x-auto">
      <table className="min-w-[540px] w-full text-sm text-left">
        <caption className="text-left font-semibold mb-2">Historical coverage</caption>
        <thead>
          <tr>
            <th>Input</th>
            <th>Recorded</th>
            <th>Used</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, count, explanation]) => (
            <tr key={name} className="border-t border-gray-200 dark:border-gray-700">
              <th className="py-2 pr-3">{name}</th>
              <td className="pr-3">{count}</td>
              <td>{explanation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default CoverageTable;
