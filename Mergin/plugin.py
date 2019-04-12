# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

import sip
import os
import shutil
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsApplication,
    QgsDataItem,
    QgsDataCollectionItem,
    QgsErrorItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsProject
)
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QApplication
from qgis.PyQt.QtCore import QSettings, Qt
from urllib.error import URLError

from .configuration_dialog import ConfigurationDialog
from .create_project_dialog import CreateProjectDialog
from .client import MerginClient
from .utils import auth_ok, find_qgis_files

icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/FA_icons")


class MerginPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.data_item_provider = None
        self.actions = []
        self.menu = u'Mergin Plugin'

    def initGui(self):
        self.data_item_provider = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.data_item_provider)

    def unload(self):
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.data_item_provider)
        self.data_item_provider = None


class MerginProjectItem(QgsDataItem):
    """ Data item to represent a Mergin project. """

    def __init__(self, parent, project_name):
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, project_name, "/Mergin/" + project_name)
        self.project_name = project_name
        settings = QSettings()
        self.path = settings.value('Mergin/localProjects/{}/path'.format(self.project_name), None)
        # check local project dir was not unintentionally removed
        if self.path:
            if not os.path.exists(self.path):
                self.path = None
        
        if self.path:
            self.setIcon(QIcon(os.path.join(icon_path, "folder-solid.svg")))
        else:
            self.setIcon(QIcon(os.path.join(icon_path, "cloud-solid.svg")))

    def download(self):
        parent_dir = QFileDialog.getExistingDirectory(None, "Open Directory", "", QFileDialog.ShowDirsOnly)
        if not parent_dir:
            return

        target_dir = os.path.join(parent_dir, self.project_name)
        settings = QSettings()
        url = settings.value('Mergin/URL', 'https://public.cloudmergin.com')
        username = settings.value('Mergin/username', '')
        password = settings.value('Mergin/password', '')
        mc = MerginClient(url, username, password)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            mc.download_project(self.project_name, target_dir)
            settings.setValue('Mergin/localProjects/{}/path'.format(self.project_name), target_dir)
            self.path = target_dir
            self.setIcon(QIcon(os.path.join(icon_path, "folder-solid.svg")))
            QApplication.restoreOverrideCursor()

            msg = "Your project {} has been successfully downloaded. " \
                  "Do you want to open project file?".format(self.project_name)
            btn_reply = QMessageBox.question(None, 'Project download', msg,
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if btn_reply == QMessageBox.Yes:
                self.open_project()
        except (URLError, ValueError):
            QApplication.restoreOverrideCursor()
            msg = "Failed to download your project {}.\n" \
                  "Please make sure your Mergin settings are correct".format(self.project_name)
            QMessageBox.critical(None, 'Project download', msg, QMessageBox.Close)

    def remove_local_project(self):
        if not self.path:
            return

        msg = "Your local changes will be lost. Make sure your project is synchronised with server. \n\n" \
              "Do you want to proceed?".format(self.project_name)
        btn_reply = QMessageBox.question(None, 'Remove local project', msg,
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if btn_reply == QMessageBox.No:
            return

        if os.path.exists(self.path):
            shutil.rmtree(self.path)
        settings = QSettings()
        settings.remove('Mergin/localProjects/{}/path'.format(self.project_name))
        self.path = None
        self.setIcon(QIcon(os.path.join(icon_path, "cloud-solid.svg")))

    def open_project(self):
        if not self.path:
            return 

        qgis_files = find_qgis_files(self.path)
        if len(qgis_files) == 1:
            QgsProject.instance().read(qgis_files[0])
        else:
            msg = "Plugin can only load project with single QGIS file but {} found.".format(len(qgis_files))
            QMessageBox.warning(None, 'Load QGIS project', msg, QMessageBox.Close)

    def actions(self, parent):
        action_download = QAction(QIcon(os.path.join(icon_path, "cloud-download-alt-solid.svg")), "Download", parent)
        action_download.triggered.connect(self.download)

        action_remove_local = QAction(QIcon(os.path.join(icon_path, "trash-solid.svg")), "Remove locally", parent)
        action_remove_local.triggered.connect(self.remove_local_project)

        action_open_project = QAction("Open QGIS project", parent)
        action_open_project.triggered.connect(self.open_project)

        if self.path:
            actions = [action_open_project, action_remove_local]
        else:
            actions = [action_download]
        return actions


class MerginRootItem(QgsDataCollectionItem):
    """ Mergin root data item with configuration dialog. """

    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "Mergin", "/Mergin")
        self.setIcon(QIcon(os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/icon.png")))

    def createChildren(self):
        settings = QSettings()
        url = settings.value('Mergin/URL', 'https://public.cloudmergin.com')
        # TODO replace with something safer
        username = settings.value('Mergin/username', '')
        password = settings.value('Mergin/password', '')

        if not auth_ok(url, username, password):
            error_item = QgsErrorItem(self, "Failed to get projects from server", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]

        mc = MerginClient(url, username, password)
        try:
            projects = mc.projects_list(['valid_qgis'])
        except URLError:
            error_item = QgsErrorItem(self, "Failed to get projects from server", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        except Exception as err:
            error_item = QgsErrorItem(self, "Error: {}".format(str(err)), "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]

        items = []
        for project in projects:
            item = MerginProjectItem(self, project['name'])
            item.setState(QgsDataItem.Populated)  # make it non-expandable
            sip.transferto(item, self)
            items.append(item)
        return items

    def configure(self):
        dlg = ConfigurationDialog()
        if dlg.exec_():
            dlg.writeSettings()

    def create_project(self):
        dlg = CreateProjectDialog()
        if dlg.exec_():
            dlg.create_project()
            self.refresh()

    def actions(self, parent):
        action_configure = QAction(QIcon(os.path.join(icon_path, "cog-solid.svg")), "Configure", parent)
        action_configure.triggered.connect(self.configure)

        action_refresh = QAction(QIcon(os.path.join(icon_path, "redo-solid.svg")), "Reload", parent)
        action_refresh.triggered.connect(self.refresh)

        action_create = QAction(QIcon(os.path.join(icon_path, "plus-square-solid.svg")), "Create new project", parent)
        action_create.triggered.connect(self.create_project)
        return [action_configure, action_refresh, action_create]


class DataItemProvider(QgsDataItemProvider):

    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return "MerginProvider"

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parentItem):
        if not parentItem:
            ri = MerginRootItem()
            sip.transferto(ri, None)
            return ri
        else:
            return None

