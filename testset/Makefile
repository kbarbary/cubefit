DATADIR = data
RESULTDIR = results
DIAGDIR = diagnostics
PLOTDIR = plots
LOGLEVEL = info
LOGFILE = N
ifeq ($(LOGFILE), Y)
LOGFILEARG = --logfile=$(RESULTDIR)/$*.log
else
LOGFILEARG = 
endif

names = PTF09fox_B PTF09fox_R \
	SN2006ob_B SN2006ob_R \
	SNF20060512-002_B SNF20060512-002_R \
	SNF20060609-002_B SNF20060609-002_R \
	SNF20061009-008_B SNF20061009-008_R \
	SNF20070429-000_B SNF20070429-000_R \
	SNF20070831-015_B SNF20070831-015_R \
	SNF20070902-021_B SNF20070902-021_R \
	SNF20080707-012_B SNF20080707-012_R \
	SNF20080717-000_B SNF20080717-000_R \
	SNF20080720-001_B SNF20080720-001_R \
	SNF20080725-004_B SNF20080725-004_R

$(names) : % : $(RESULTDIR)/%.fits

all: $(names)

$(RESULTDIR)/%.fits :
	mkdir -p $(RESULTDIR)
	mkdir -p $(DIAGDIR)/$*
	cubefit $(DATADIR)/$*/$*.json \
        $(RESULTDIR)/$*.fits \
        --dataprefix=$(DATADIR)/$* \
        --diagdir=$(DIAGDIR)/$* \
        --loglevel=$(LOGLEVEL) $(LOGFILEARG)\
        --mu_wave=0.07 \
        --mu_xy=0.001

$(foreach name,$(names),$(name)-plots) : %-plots : $(PLOTDIR)/%_timeseries.eps $(PLOTDIR)/%_waveslice.eps

$(PLOTDIR)/%_B_timeseries.eps $(PLOTDIR)/%_B_waveslice.eps :
	mkdir -p $(PLOTDIR)
	cubefit-plot \
	$(DATADIR)/$*_B/$*_B.json \
	$(RESULTDIR)/$*_B.fits \
	$(PLOTDIR)/$*_B \
	--band=B \
	--dataprefix=$(DATADIR)/$*_B \
	--diagdir=$(DIAGDIR)/$*_B

$(PLOTDIR)/%_R_timeseries.eps $(PLOTDIR)/%_R_waveslice.eps :
	mkdir -p $(PLOTDIR)
	cubefit-plot \
	$(DATADIR)/$*_R/$*_R.json \
	$(RESULTDIR)/$*_R.fits \
	$(PLOTDIR)/$*_R \
	--band=V \
	--dataprefix=$(DATADIR)/$*_R \
	--diagdir=$(DIAGDIR)/$*_R