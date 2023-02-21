properties([
    buildDiscarder(
        logRotator(
            artifactDaysToKeepStr: '',
            artifactNumToKeepStr: '',
            daysToKeepStr: '14',
            numToKeepStr: '10',
        )
    ),
    // Make new builds terminate existing builds
    disableConcurrentBuilds(
        abortPrevious: true,
    )
])
pipeline {
    agent {
        // To run on a specific node, e.g. for a specific architecture, add `label '...'`.
        docker {
            alwaysPull true
            image 'lsstts/develop-env:develop'
            args "--entrypoint=''"
        }
    }
    environment {
        // Python module name.
        MODULE_NAME = "lsst.ts.salobj"
        // Space-separated list of SAL component names for all IDL files required.
        IDL_NAMES = "Test Script LOVE"
        // Product name for documentation upload; the associated
        // documentation site is `https://{DOC_PRODUCT_NAME}.lsst.io`.
        DOC_PRODUCT_NAME = "ts-salobj"

        WORK_BRANCHES = "${GIT_BRANCH} ${CHANGE_BRANCH} develop"
        LSST_IO_CREDS = credentials('lsst-io')
        XML_REPORT_PATH = 'jenkinsReport/report.xml'
    }
    stages {
        stage ('Update branches of required packages') {
            steps {
                // When using the docker container, we need to change the WHOME path
                // to WORKSPACE to have the authority to install the packages.
                withEnv(["WHOME=${env.WORKSPACE}"]) {
                    sh """
                        source /home/saluser/.setup_dev.sh || echo "Loading env failed; continuing..."

                        # Update base required packages
                        cd /home/saluser/repos/ts_idl
                        /home/saluser/.checkout_repo.sh ${WORK_BRANCHES}
                        git pull

                        cd /home/saluser/repos/ts_sal
                        /home/saluser/.checkout_repo.sh ${WORK_BRANCHES}
                        git pull

                        cd /home/saluser/repos/ts_utils
                        /home/saluser/.checkout_repo.sh ${WORK_BRANCHES}
                        git pull

                        cd /home/saluser/repos/ts_xml
                        /home/saluser/.checkout_repo.sh ${WORK_BRANCHES}
                        git pull

                        # Update additional required packages
                        cd /home/saluser/repos/ts_config_ocs
                        /home/saluser/.checkout_repo.sh ${WORK_BRANCHES}
                        git pull

                        # Make IDL files
                        make_idl_files.py ${env.IDL_NAMES}
                    """
                }
            }
        }
        stage('Run unit tests') {
            steps {
                withEnv(["WHOME=${env.WORKSPACE}"]) {
                    sh """
                        source /home/saluser/.setup_dev.sh || echo "Loading env failed; continuing..."
                        setup -r .
                        pytest --cov-report html --cov=${env.MODULE_NAME} --junitxml=${env.XML_REPORT_PATH}
                    """
                }
            }
        }
        stage('Build documentation') {
            steps {
                withEnv(["WHOME=${env.WORKSPACE}"]) {
                    sh """
                        source /home/saluser/.setup_dev.sh || echo "Loading env failed; continuing..."
                        setup -r .
                        package-docs build
                    """
                }
            }
        }
        stage('Try to upload documentation') {
            steps {
                withEnv(["WHOME=${env.WORKSPACE}"]) {
                    catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                        sh '''
                            source /home/saluser/.setup_dev.sh || echo "Loading env failed; continuing..."
                            setup -r .
                            ltd -u ${LSST_IO_CREDS_USR} -p ${LSST_IO_CREDS_PSW} upload \
                                --product ${DOC_PRODUCT_NAME} --git-ref ${GIT_BRANCH} --dir doc/_build/html
                        '''
                    }
                }
            }
        }
    }
    post {
        always {
            // The path of xml needed by JUnit is relative to the workspace.
            junit 'jenkinsReport/*.xml'

            // Publish the HTML report.
            publishHTML (
                target: [
                    allowMissing: false,
                    alwaysLinkToLastBuild: false,
                    keepAll: true,
                    reportDir: 'jenkinsReport',
                    reportFiles: 'index.html',
                    reportName: "Coverage Report"
                ]
            )
        }
        cleanup {
            // Clean up the workspace.
            deleteDir()
        }
    }
}
