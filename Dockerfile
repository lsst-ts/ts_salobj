ARG base_image_tag

FROM lsstts/salobj:$base_image_tag

# Arguments for package versions
ARG config_ocs_v="develop"
ARG sal_v="develop"
ARG salobj_v="develop"
ARG xml_v="develop"
ARG idl_v="develop"

WORKDIR /home/saluser/repos/ts_config_ocs
RUN /home/saluser/.checkout_repo.sh ${config_ocs_v}

WORKDIR /home/saluser/repos/ts_sal
RUN /home/saluser/.checkout_repo.sh ${sal_v}

WORKDIR /home/saluser/repos/ts_salobj
RUN /home/saluser/.checkout_repo.sh ${salobj_v}

WORKDIR /home/saluser/repos/ts_xml
RUN /home/saluser/.checkout_repo.sh ${xml_v}

WORKDIR /home/saluser/repos/ts_idl
RUN /home/saluser/.checkout_repo.sh ${idl_v}

WORKDIR /home/saluser/repos/ts_sal
RUN source /opt/lsst/software/stack/loadLSST.bash && setup lsst_distrib && \
    source /home/saluser/repos/ts_sal/setup.env && \
    setup ts_sal -t current && \
    scons

WORKDIR /home/saluser/repos/ts_idl
RUN source /opt/lsst/software/stack/loadLSST.bash && setup lsst_distrib && \
    source /home/saluser/repos/ts_sal/setup.env && \
    setup ts_sal -t current && \
    setup ts_idl -t current && scons

WORKDIR /home/saluser/
RUN source /opt/lsst/software/stack/loadLSST.bash && setup lsst_distrib && \
    source /home/saluser/repos/ts_sal/setup.env && \
    setup ts_sal -t current && \
    setup ts_idl -t current && \
    make_idl_files.py Test Script && \
    make_salpy_libs.py Test Script

WORKDIR /home/saluser/repos/ts_salobj
RUN source /opt/lsst/software/stack/loadLSST.bash && setup lsst_distrib && \
    source /home/saluser/repos/ts_sal/setup.env && \
    setup ts_sal -t current && \
    setup ts_idl -t current && \
    setup ts_salobj -t current && \
    scons --clean && scons || py.test
