import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'src/_generated'] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      react.configs.flat.recommended,
      react.configs.flat['jsx-runtime'],
    ],
    files: ['**/*.{ts,tsx}'],
    linterOptions: { reportUnusedDisableDirectives: 'error' },
    languageOptions: {
      ecmaVersion: 2021,
      globals: globals.browser,
    },
    settings: {
      react: { version: '18.3' },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      'react/prop-types': 'off',
      'react/no-array-index-key': 'error',
      quotes: ['error', 'single', { avoidEscape: true, allowTemplateLiterals: true }],
      'jsx-quotes': ['error', 'prefer-double'],
      'no-restricted-syntax': [
        'error',
        {
          selector:
            'JSXOpeningElement[name.name="input"] > JSXAttribute[name.name="type"][value.value=/^(date|datetime-local|time)$/]',
          message:
            'Native date and time inputs are banned; use the shared DatePicker (docs/design-system.md).',
        },
        {
          selector:
            "BinaryExpression[operator=/^[!=]==?$/]:has(MemberExpression[property.name='status']):has(Literal[raw=/^[1-5]\\d\\d$/])",
          message:
            'Compare HTTP statuses with StatusCodes.* from http-status-codes (api/client.ts does).',
        },
        {
          selector: "NewExpression[callee.name='Date'] > Literal[value=/^\\d{4}-\\d{2}-\\d{2}$/]",
          message:
            'new Date(\'YYYY-MM-DD\') parses as UTC midnight; use parseISODateLocal() from utils.ts.',
        },
        {
          selector:
            "CallExpression[callee.property.name=/^(slice|substring|replace)$/][callee.object.callee.name='formatMoney']",
          message:
            'Do not edit a formatted price; use formatMoney(cents, locale, { symbol: false }) (lib/organizerPromotions.ts).',
        },
      ],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
)
