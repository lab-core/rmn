// Karma configuration file, see link for more information
// https://karma-runner.github.io/1.0/config/configuration-file.html
//
// Local: `npm test` opens Chrome and re-runs on change.
// CI:    `npx ng test --watch=false --browsers=ChromeHeadlessCI`

module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma')
    ],
    client: {
      jasmine: {
        // https://jasmine.github.io/api/edge/Configuration.html
        random: true,
        timeoutInterval: 10000 // a single spec may not run longer than 10 s
      },
      clearContext: false // leave Jasmine Spec Runner output visible in browser
    },
    // a browser that stops reporting or never starts ends the run instead of
    // stalling the CI job until its timeout
    captureTimeout: 60000,
    browserNoActivityTimeout: 60000,
    browserDisconnectTimeout: 10000,
    browserDisconnectTolerance: 1,
    jasmineHtmlReporter: {
      suppressAll: true // removes the duplicated traces
    },
    coverageReporter: {
      dir: require('path').join(__dirname, './coverage/rmn'),
      subdir: '.',
      reporters: [
        { type: 'html' },
        { type: 'text-summary' },
        // read by the CI job summary
        { type: 'json-summary' }
      ],
      // the run fails below these: raise them with the coverage, never lower them
      check: {
        global: { statements: 94, branches: 89, functions: 91, lines: 94 }
      }
    },
    reporters: ['progress', 'kjhtml'],
    port: 9876,
    colors: true,
    logLevel: config.LOG_INFO,
    autoWatch: true,
    browsers: ['Chrome'],
    customLaunchers: {
      // --no-sandbox: Chrome refuses to start its sandbox under the CI runner's
      // container user; the tests are our own code, not untrusted pages.
      ChromeHeadlessCI: {
        base: 'ChromeHeadless',
        flags: ['--no-sandbox', '--disable-gpu']
      }
    },
    singleRun: false,
    restartOnFileChange: true
  });
};
