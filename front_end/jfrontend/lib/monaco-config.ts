// Configure Monaco editor language features and LSP-like functionality
export function configureMonacoLanguages(monacoInstance: any) {
  // TypeScript/JavaScript enhanced features
  configureTypeScript(monacoInstance)
  
  // Python language features
  configurePython(monacoInstance)
  
  // Java language features
  configureJava(monacoInstance)
  
  // C/C++ language features
  configureCpp(monacoInstance)
  
  // Go language features
  configureGo(monacoInstance)
  
  // Rust language features
  configureRust(monacoInstance)
}

function configureTypeScript(monaco: any) {
  // Enhanced TypeScript configuration
  monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
    target: monaco.languages.typescript.ScriptTarget.Latest,
    allowNonTsExtensions: true,
    moduleResolution: monaco.languages.typescript.ModuleResolutionKind.NodeJs,
    module: monaco.languages.typescript.ModuleKind.CommonJS,
    noEmit: true,
    esModuleInterop: true,
    jsx: monaco.languages.typescript.JsxEmit.React,
    reactNamespace: 'React',
    allowJs: true,
    typeRoots: ['node_modules/@types']
  })

  // Add React type definitions
  const reactTypes = `
    declare module 'react' {
      export interface Component<P = {}, S = {}> {}
      export function useState<T>(initialState: T): [T, (value: T) => void];
      export function useEffect(effect: () => void, deps?: any[]): void;
      export function useCallback<T extends (...args: any[]) => any>(callback: T, deps: any[]): T;
      export function useMemo<T>(factory: () => T, deps: any[]): T;
      export const Fragment: any;
    }
  `
  
  monaco.languages.typescript.typescriptDefaults.addExtraLib(
    reactTypes,
    'file:///node_modules/@types/react/index.d.ts'
  )

  // Add Node.js type definitions
  const nodeTypes = `
    declare const console: {
      log(...args: any[]): void;
      error(...args: any[]): void;
      warn(...args: any[]): void;
      info(...args: any[]): void;
    };
    declare const process: {
      env: { [key: string]: string | undefined };
      argv: string[];
      cwd(): string;
    };
  `
  
  monaco.languages.typescript.typescriptDefaults.addExtraLib(
    nodeTypes,
    'file:///node_modules/@types/node/index.d.ts'
  )
}

function configurePython(monaco: any) {
  // Python language configuration
  monaco.languages.setLanguageConfiguration('python', {
    comments: {
      lineComment: '#',
      blockComment: ['"""', '"""']
    },
    brackets: [
      ['{', '}'],
      ['[', ']'],
      ['(', ')']
    ],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"', notIn: ['string'] },
      { open: "'", close: "'", notIn: ['string', 'comment'] }
    ],
    surroundingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"' },
      { open: "'", close: "'" }
    ],
    indentationRules: {
      increaseIndentPattern: /^\s*(def|class|if|elif|else|for|while|with|try|except|finally|async def).*:\s*$/,
      decreaseIndentPattern: /^\s*(elif|else|except|finally)\b.*$/
    }
  })

  // Python completion provider with built-in functions and keywords
  monaco.languages.registerCompletionItemProvider('python', {
    provideCompletionItems: (model: any, position: any) => {
      const suggestions = [
        // Built-in functions
        ...pythonBuiltins.map(builtin => ({
          label: builtin.name,
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: builtin.snippet,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: builtin.description,
          range: getWordRange(model, position)
        })),
        // Keywords
        ...pythonKeywords.map(keyword => ({
          label: keyword,
          kind: monaco.languages.CompletionItemKind.Keyword,
          insertText: keyword,
          range: getWordRange(model, position)
        }))
      ]
      return { suggestions }
    }
  })
}

function configureJava(monaco: any) {
  monaco.languages.setLanguageConfiguration('java', {
    comments: {
      lineComment: '//',
      blockComment: ['/*', '*/']
    },
    brackets: [
      ['{', '}'],
      ['[', ']'],
      ['(', ')']
    ],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"', notIn: ['string'] },
      { open: "'", close: "'", notIn: ['string', 'comment'] }
    ]
  })

  monaco.languages.registerCompletionItemProvider('java', {
    provideCompletionItems: (model: any, position: any) => {
      const suggestions = [
        {
          label: 'System.out.println',
          kind: monaco.languages.CompletionItemKind.Method,
          insertText: 'System.out.println(${1:message});',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Print a line to the console',
          range: getWordRange(model, position)
        },
        {
          label: 'public class',
          kind: monaco.languages.CompletionItemKind.Class,
          insertText: 'public class ${1:ClassName} {\n\t${2:// class body}\n}',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Create a public class',
          range: getWordRange(model, position)
        },
        {
          label: 'public static void main',
          kind: monaco.languages.CompletionItemKind.Method,
          insertText: 'public static void main(String[] args) {\n\t${1:// main method body}\n}',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Main method entry point',
          range: getWordRange(model, position)
        }
      ]
      return { suggestions }
    }
  })
}

function configureCpp(monaco: any) {
  monaco.languages.setLanguageConfiguration('cpp', {
    comments: {
      lineComment: '//',
      blockComment: ['/*', '*/']
    },
    brackets: [
      ['{', '}'],
      ['[', ']'],
      ['(', ')'],
      ['<', '>']
    ],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '<', close: '>', notIn: ['string', 'comment'] },
      { open: '"', close: '"', notIn: ['string'] },
      { open: "'", close: "'", notIn: ['string', 'comment'] }
    ]
  })

  monaco.languages.registerCompletionItemProvider('cpp', {
    provideCompletionItems: (model: any, position: any) => {
      const suggestions = [
        {
          label: 'std::cout',
          kind: monaco.languages.CompletionItemKind.Variable,
          insertText: 'std::cout << ${1:value} << std::endl;',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Output to console',
          range: getWordRange(model, position)
        },
        {
          label: '#include <iostream>',
          kind: monaco.languages.CompletionItemKind.Module,
          insertText: '#include <iostream>',
          documentation: 'Include iostream header',
          range: getWordRange(model, position)
        },
        {
          label: 'int main()',
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: 'int main() {\n\t${1:// main function body}\n\treturn 0;\n}',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Main function',
          range: getWordRange(model, position)
        }
      ]
      return { suggestions }
    }
  })
}

function configureGo(monaco: any) {
  monaco.languages.setLanguageConfiguration('go', {
    comments: {
      lineComment: '//',
      blockComment: ['/*', '*/']
    },
    brackets: [
      ['{', '}'],
      ['[', ']'],
      ['(', ')']
    ],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"', notIn: ['string'] },
      { open: "'", close: "'", notIn: ['string', 'comment'] },
      { open: '`', close: '`', notIn: ['string', 'comment'] }
    ]
  })

  monaco.languages.registerCompletionItemProvider('go', {
    provideCompletionItems: (model: any, position: any) => {
      const suggestions = [
        {
          label: 'fmt.Println',
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: 'fmt.Println(${1:value})',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Print to console',
          range: getWordRange(model, position)
        },
        {
          label: 'func main()',
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: 'func main() {\n\t${1:// main function body}\n}',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Main function',
          range: getWordRange(model, position)
        },
        {
          label: 'package main',
          kind: monaco.languages.CompletionItemKind.Module,
          insertText: 'package main',
          documentation: 'Package declaration',
          range: getWordRange(model, position)
        }
      ]
      return { suggestions }
    }
  })
}

function configureRust(monaco: any) {
  monaco.languages.setLanguageConfiguration('rust', {
    comments: {
      lineComment: '//',
      blockComment: ['/*', '*/']
    },
    brackets: [
      ['{', '}'],
      ['[', ']'],
      ['(', ')']
    ],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"', notIn: ['string'] },
      { open: "'", close: "'", notIn: ['string', 'comment'] }
    ]
  })

  monaco.languages.registerCompletionItemProvider('rust', {
    provideCompletionItems: (model: any, position: any) => {
      const suggestions = [
        {
          label: 'println!',
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: 'println!("${1:message}");',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Print to console',
          range: getWordRange(model, position)
        },
        {
          label: 'fn main()',
          kind: monaco.languages.CompletionItemKind.Function,
          insertText: 'fn main() {\n\t${1:// main function body}\n}',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Main function',
          range: getWordRange(model, position)
        },
        {
          label: 'let',
          kind: monaco.languages.CompletionItemKind.Keyword,
          insertText: 'let ${1:variable} = ${2:value};',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          documentation: 'Variable declaration',
          range: getWordRange(model, position)
        }
      ]
      return { suggestions }
    }
  })
}

// Setup LSP-like features for enhanced development experience
export function setupLSPFeatures(monaco: any, language: string) {
  // Hover provider for documentation
  monaco.languages.registerHoverProvider(language, {
    provideHover: (model: any, position: any) => {
      const word = model.getWordAtPosition(position)
      if (!word) return null

      const documentation = getDocumentation(language, word.word)
      if (!documentation) return null

      return {
        range: new monaco.Range(
          position.lineNumber,
          word.startColumn,
          position.lineNumber,
          word.endColumn
        ),
        contents: [
          { value: `**${word.word}**` },
          { value: documentation }
        ]
      }
    }
  })

  // Signature help provider
  monaco.languages.registerSignatureHelpProvider(language, {
    signatureHelpTriggerCharacters: ['(', ','],
    provideSignatureHelp: (model: any, position: any) => {
      const signatures = getSignatureHelp(language, model, position)
      return {
        value: {
          signatures,
          activeSignature: 0,
          activeParameter: 0
        },
        dispose: () => {}
      }
    }
  })

  // Definition provider for go-to-definition
  monaco.languages.registerDefinitionProvider(language, {
    provideDefinition: (model: any, position: any) => {
      // This would typically connect to a language server
      // For now, we'll provide basic local definitions
      return null
    }
  })
}

// Helper function to get word range
function getWordRange(model: any, position: any) {
  const word = model.getWordUntilPosition(position)
  return {
    startLineNumber: position.lineNumber,
    endLineNumber: position.lineNumber,
    startColumn: word.startColumn,
    endColumn: word.endColumn
  }
}

// Python built-in functions and keywords
const pythonBuiltins = [
  { name: 'print', snippet: 'print(${1:value})', description: 'Print values to stdout' },
  { name: 'len', snippet: 'len(${1:obj})', description: 'Return the length of an object' },
  { name: 'range', snippet: 'range(${1:stop})', description: 'Return a sequence of numbers' },
  { name: 'str', snippet: 'str(${1:obj})', description: 'Return a string representation' },
  { name: 'int', snippet: 'int(${1:value})', description: 'Convert to integer' },
  { name: 'float', snippet: 'float(${1:value})', description: 'Convert to float' },
  { name: 'list', snippet: 'list(${1:iterable})', description: 'Create a list' },
  { name: 'dict', snippet: 'dict(${1:mapping})', description: 'Create a dictionary' },
  { name: 'open', snippet: 'open(${1:file}, ${2:mode})', description: 'Open a file' },
  { name: 'input', snippet: 'input(${1:prompt})', description: 'Read user input' }
]

const pythonKeywords = [
  'and', 'as', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else',
  'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda',
  'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield', 'async', 'await'
]

// Get documentation for symbols
function getDocumentation(language: string, symbol: string): string | null {
  const docs: { [lang: string]: { [symbol: string]: string } } = {
    python: {
      'print': 'print(*values, sep=" ", end="\\n", file=sys.stdout, flush=False)\nPrint values to a stream, or to sys.stdout by default.',
      'len': 'len(obj)\nReturn the number of items in a container.',
      'range': 'range(stop) or range(start, stop[, step])\nCreate an object which is an iterable of integers.',
      'str': 'str(object="") or str(object=b"", encoding="utf-8", errors="strict")\nReturn a string version of object.',
      'int': 'int([x]) or int(x, base=10)\nReturn an integer object constructed from a number or string.',
      'float': 'float([x])\nReturn a floating point number constructed from a number or string.',
      'list': 'list([iterable])\nReturn a list whose items are the same and in the same order as iterable\'s items.',
      'dict': 'dict(**kwarg) or dict(mapping, **kwarg) or dict(iterable, **kwarg)\nCreate a new dictionary.',
      'open': 'open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None)\nOpen file and return a stream.',
      'input': 'input([prompt])\nRead a string from standard input.'
    },
    javascript: {
      'console': 'The console object provides access to the browser\'s debugging console.',
      'console.log': 'console.log(obj1 [, obj2, ..., objN])\nOutputs a message to the Web Console.',
      'function': 'function name([param[, param[, ... param]]]) { statements }',
      'const': 'const name1 = value1 [, name2 = value2 [, ... [, nameN = valueN]]];',
      'let': 'let var1 [= value1] [, var2 [= value2]] [, ..., varN [= valueN]];',
      'var': 'var varname1 [= value1] [, varname2 [= value2] ... [, varnameN [= valueN]]];'
    },
    typescript: {
      'interface': 'interface InterfaceName { propertyName: type; }',
      'type': 'type TypeName = string | number;',
      'class': 'class ClassName { constructor() {} }',
      'enum': 'enum EnumName { VALUE1, VALUE2 }'
    }
  }

  return docs[language]?.[symbol] || null
}

// Get signature help information
function getSignatureHelp(language: string, model: any, position: any) {
  // This would typically analyze the context and provide relevant signatures
  // For now, return empty array
  return []
}