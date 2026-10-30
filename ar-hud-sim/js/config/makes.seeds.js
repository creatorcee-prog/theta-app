// Good designs found by earlier searches, used to warm-start the next one.
export const SEEDS = {
  atlas: [{ prism: 10, lens: 'acl1512', flip: false, stop: 11.4, az: 43.7, el: 30, tilt: 9.1, inset: 2 }, { prism: 8, lens: 'eo19', flip: false, stop: 7.9, az: 34, el: -20, tilt: 6, inset: 4 }],
  solo: [{ prism: 6, lens: 'eo19', flip: false, stop: 4.7, az: 33.2, el: 13.3, tilt: 7.6, inset: 4.2 }, { prism: 10, lens: 'eo19', flip: false, stop: 10.5, az: 35.5, el: 16, tilt: 7.3, inset: 2.5 }],
  kestrel: [{ prism: 10, lens: 'eo19', flip: true, stop: 11.7, az: 26.2, el: 24.2, tilt: 7.9, inset: 5 }],
  mirage: [{ lens: 'cb45', coat: 'bare', relay: true, fsize: 12, fdist: 22, trim: 12, stop: 10, diam: 18, fold: 90, throw: 52, az: 30, el: -15, tx: 0, ty: 0, stilt: 0, flip: false, radius: 1000 }, { lens: 'cb45', coat: 'bare', relay: true, fsize: 12, fdist: 23, trim: 12, stop: 10, diam: 15, fold: 90, throw: 52, az: 30, el: -10, tx: 0, ty: 0, stilt: 0, flip: false, radius: 1000 }],
  mirageCoat: [{ lens: 'cb45', coat: 'coated', relay: false, fsize: 10, fdist: 22, trim: 10, flip: false, stop: 8, az: 48, el: -2, throw: 50, tx: 0, ty: 0 }, { lens: 'cb45', coat: 'bare', relay: false, fsize: 10, fdist: 22, trim: 10, flip: false, stop: 8, az: 46, el: 0, throw: 45, tx: 0, ty: 0 }],
  mirageCast: [{ lens: 'cb45', relay: false, fsize: 10, fdist: 22, trim: 10, flip: false, stop: 8, az: 31.7, el: -1.9, fold: 60, stilt: 0, throw: 50, tx: 3.5, ty: 1.6, diam: 8, thick: 8 }],
  lumen: [{ lens: 'eo19', flip: false, stop: 6, az: 20, el: 5, thick: 3.5, guide: 55, facets: 3, spacing: 3.5, height: 14, margin: -4 }],
  wisp: [{ prism: 8, lens: 'eo19', flip: false, stop: 6.5, az: 37.9, el: -26, tilt: 5.9, inset: 4 }, { prism: 6, lens: 'eo19', flip: false, stop: 5.9, az: 28, el: 17.4, tilt: 3.6, inset: 0 }],
};
