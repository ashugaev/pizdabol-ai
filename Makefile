HOST=root@146.190.110.77
APP_DIR=/opt/noter
PYTHON ?= .venv/bin/python

deploy:
	git push
	ssh $(HOST) "cd $(APP_DIR) && git pull && systemctl restart noter && systemctl status noter --no-pager"

dev:
	ssh $(HOST) "systemctl stop noter"
	.venv/bin/python bot.py

stop-dev:
	ssh $(HOST) "systemctl start noter"

test:
	$(PYTHON) -m py_compile bot.py config.py services/*.py tests/*.py
	$(PYTHON) -m unittest discover -s tests -v
