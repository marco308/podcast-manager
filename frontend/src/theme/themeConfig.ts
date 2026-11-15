import { theme, type ThemeConfig } from 'antd';

// The Parts List world (see .impeccable/surfaces/frontend-src.md and DESIGN.md).
// Panels are square-cornered sheets; buttons are pills. Outfit is the voice,
// DM Mono labels and specs. Orange is the one signal colour.

export const palette = {
  dark: {
    ground: '#16191D', // cool graphite
    panel: '#1F2328',
    raised: '#272C33',
    ink: '#EEF0F2',
    inkSecondary: 'rgba(238, 240, 242, 0.74)',
    rule: 'rgba(238, 240, 242, 0.22)',
    accent: '#E8590C',
    accentText: '#FF7A33', // orange that reads as text on graphite
    onAccent: '#16191D',
    balloon: '#62A3EA',
    serial: '#F5C12E',
    ok: '#4FE06A',
    partial: '#F5C12E',
    failed: '#FF5A4A',
    off: '#4A5059',
  },
  light: {
    ground: '#F2F3F5', // cool drawing-sheet grey
    panel: '#FFFFFF',
    raised: '#E8EAEE',
    ink: '#16191D',
    inkSecondary: 'rgba(22, 25, 29, 0.70)',
    rule: 'rgba(22, 25, 29, 0.22)',
    accent: '#C24A08',
    accentText: '#B04306',
    onAccent: '#FFFFFF',
    balloon: '#2F6FC4',
    serial: '#B07F00',
    ok: '#1E9E4A',
    partial: '#B07F00',
    failed: '#D0312D',
    off: '#B4B9C1',
  },
} as const;

const fontFamily = "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif";
export const monoFamily = "'DM Mono', ui-monospace, Menlo, monospace";

function build(mode: 'light' | 'dark'): ThemeConfig {
  const p = palette[mode];
  return {
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: p.accent,
      colorLink: p.ink,
      colorLinkHover: p.accentText,
      colorInfo: p.balloon,
      colorSuccess: p.ok,
      colorWarning: p.partial,
      colorError: p.failed,
      colorText: p.ink,
      colorTextSecondary: p.inkSecondary,
      colorBgLayout: p.ground,
      colorBgContainer: p.panel,
      colorBgElevated: p.panel,
      colorBorder: p.rule,
      colorBorderSecondary: p.rule,
      fontFamily,
      fontSize: 15,
      borderRadius: 0,
      borderRadiusLG: 0,
      borderRadiusSM: 0,
      controlHeight: 36,
      wireframe: false,
    },
    components: {
      Button: {
        borderRadius: 999,
        borderRadiusLG: 999,
        borderRadiusSM: 999,
        fontWeight: 600,
        primaryColor: p.onAccent,
        primaryShadow: 'none',
        defaultShadow: 'none',
        defaultBorderColor: p.ink,
        defaultColor: p.ink,
        defaultBg: 'transparent',
      },
      Layout: {
        headerBg: p.ground,
        siderBg: p.ground,
        bodyBg: p.ground,
      },
      Menu: {
        itemBg: 'transparent',
        itemSelectedBg: p.panel,
        itemSelectedColor: p.ink,
        itemBorderRadius: 0,
        itemMarginInline: 0,
        itemHoverBg: p.raised,
      },
      Card: { headerFontSize: 18 },
      Table: {
        headerBg: 'transparent',
        headerColor: p.inkSecondary,
        borderColor: p.rule,
        rowHoverBg: p.raised,
      },
      Tag: { borderRadiusSM: 999, defaultBg: 'transparent' },
      Switch: { colorPrimary: p.accent, colorPrimaryHover: p.accent },
      Segmented: { borderRadius: 999, borderRadiusSM: 999, itemSelectedBg: p.panel },
      Modal: { contentBg: p.panel, headerBg: p.panel },
    },
  };
}

export const lightTheme = build('light');
export const darkTheme = build('dark');
