properties(
    [
    buildDiscarder
        (logRotator (
            artifactDaysToKeepStr: '',
            artifactNumToKeepStr: '',
            daysToKeepStr: '14',
            numToKeepStr: '10'
        ) ),
    disableConcurrentBuilds()
    ]
)

node {
    def network_name = String.format("n_%s_%s", env.BUILD_ID, env.JENKINS_NODE_COOKIE)
    def container_name = String.format("c_%s_%s", env.BUILD_ID, env.JENKINS_NODE_COOKIE)
    def work_branches = String.format("%s %s %", env.GIT_BRANCH, env.CHANGE_BRANCH, env.develop)
    def LSST_IO_CREDS = credentials("lsst-io")
    def SQUASH_CREDS = credentials("squash")
    def containerOpt = String.format("-v %s:/home/saluser/repo/ -td --rm -e LTD_USERNAME=%s\${LSST_IO_CREDS_USR} -e LTD_PASSWORD=\${LSST_IO_CREDS_PSW}, env.WORKSPACE, LSST_IO_CREDS_USR, LSST_IO_CREDS_PSW)

    stage("Pulling docker image") {
        container = docker.image("lsstts/salobj:develop")
        container.pull()
    }

    stage("Preparing environment") {
        container=\$(docker run -v \${WORKSPACE}:/home/saluser/repo/ -td --rm --net \${network_name} -e LTD_USERNAME=\${LSST_IO_CREDS_USR} -e LTD_PASSWORD=\${LSST_IO_CREDS_PSW} --name \${container_name} lsstts/salobj:develop)
                    """
                }
            }
        }
        stage("Checkout sal") {
            steps {
                script {
                    sh "docker exec -u saluser \${container_name} sh -c \"" +
                        "source ~/.setup.sh && " +
                        "cd /home/saluser/repos/ts_sal && " +
                        "/home/saluser/.checkout_repo.sh \${work_branches} && " +
                        "git pull\""
                }
            }
        }
        stage("Checkout xml") {
            steps {
                script {
                    sh "docker exec -u saluser \${container_name} sh -c \"" +
                        "source ~/.setup.sh && " +
                        "cd /home/saluser/repos/ts_xml && " +
                        "/home/saluser/.checkout_repo.sh \${work_branches} && " +
                        "git pull\""
                }
            }
        }
        stage("Checkout IDL") {
            steps {
                script {
                    sh "docker exec -u saluser \${container_name} sh -c \"" +
                        "source ~/.setup.sh && " +
                        "source /home/saluser/.bashrc && " +
                        "cd /home/saluser/repos/ts_idl && " +
                        "/home/saluser/.checkout_repo.sh \${work_branches} && " +
                        "git pull\""
                }
            }
        }
        stage("Build IDL files") {
            steps {
                script {
                    sh "docker exec -u saluser \${container_name} sh -c \"" +
                        "source ~/.setup.sh && " +
                        "source /home/saluser/.bashrc && " +
                        "make_idl_files.py Test Script LOVE && " +
                        "make_salpy_libs.py Test\""
                }
            }
        }
        stage("Running tests") {
            steps {
                script {
                    sh "docker exec -u saluser \${container_name} sh -c \"" +
                        "source ~/.setup.sh && " +
                        "cd /home/saluser/repo/ && " +
                        "eups declare -r . -t saluser && " +
                        "setup ts_salobj -t saluser && " +
                        "export LSST_DDS_IP=192.168.0.1 && " +
                        "printenv LSST_DDS_IP && " +
                        "py.test --junitxml=tests/.tests/junit.xml\""
                }
            }
        }
    }
    post {
        always {
            // The path of xml needed by JUnit is relative to
            // the workspace.
            junit 'tests/.tests/junit.xml'

            // Publish the HTML report
            publishHTML (target: [
                allowMissing: false,
                alwaysLinkToLastBuild: false,
                keepAll: true,
                reportDir: 'tests/.tests/',
                reportFiles: 'index.html',
                reportName: "Coverage Report"
              ])
                // || echo FAILED TO PUSH DOCUMENTATION.
            sh "docker exec -u saluser \${container_name} sh -c \"" +
                "source ~/.setup.sh && " +
                "cd /home/saluser/repo/ && " +
                "setup ts_salobj -t saluser && " +
                "package-docs build\""

            script {

                def RESULT = sh returnStatus: true, script: "docker exec -u saluser \${container_name} sh -c \"" +
                    "source ~/.setup.sh && " +
                    "cd /home/saluser/repo/ && " +
                    "setup ts_salobj -t saluser && " +
                    "ltd upload --product ts-salobj --git-ref \${GIT_BRANCH} --dir doc/_build/html\""

                if ( RESULT != 0 ) {
                    unstable("Failed to push documentation.")
                }
             }
        }
        success {
            script {
                def RESULT = sh returnStatus: true, script: "docker exec -u saluser \${container_name} sh -c \"" +
                    "source ~/.setup.sh && " +
                    "setup verify && " +
                    "cd /home/saluser/repo && " +
                    "dispatch_verify.py --url https://squash-restful-api.lsst.codes " +
                        "--ignore-lsstsw --env jenkins --user=\${SQUASH_CREDS_USR} --password=\${SQUASH_CREDS_PSW} " +
                        "tests/measurements/speed.json\""

                if ( RESULT != 0 ) {
                    unstable("Failed to upload SQuaSH metrics.")
                }
            }
        }
        cleanup {
            sh """
                docker exec -u root --privileged \${container_name} sh -c \"chmod -R a+rw /home/saluser/repo/\"
                docker stop \${container_name} || echo Could not stop container
                docker network rm \${network_name} || echo Could not remove network
            """
            deleteDir()
        }
    }
}
