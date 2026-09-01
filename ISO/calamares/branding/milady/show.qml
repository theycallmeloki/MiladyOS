import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    Slide {
        Text {
            anchors.centerIn: parent
            text: qsTr("Welcome to MiladyOS.<br/>" +
                       "Booted from the live ISO. Install to disk to become " +
                       "a cluster node — master, worker or desktop.")
            wrapMode: Text.WordWrap
            width: 600
            horizontalAlignment: Text.Center
        }
    }
}
