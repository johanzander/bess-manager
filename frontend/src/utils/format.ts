// A locally-computed number (e.g. a sum or delta across several near-zero
// periods) can land on a tiny negative float that rounds to zero -- JS's
// Number.prototype.toFixed keeps the sign in that case
// ((-0.0004).toFixed(2) === "-0.00"), unlike toFixed on an already-
// negative-zero value. Round first, then add 0 to normalize -0 to 0 (IEEE
// 754: -0 + 0 === 0) before the final toFixed, so it never happens.
export const formatFixed = (value: number, prec: number): string => {
  const factor = 10 ** prec;
  const rounded = Math.round(value * factor) / factor + 0;
  return rounded.toFixed(prec);
};
